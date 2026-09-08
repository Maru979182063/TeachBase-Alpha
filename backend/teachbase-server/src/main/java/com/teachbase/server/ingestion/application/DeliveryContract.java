package com.teachbase.server.ingestion.application;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;

/** 中文维护说明：执行 G0 schema 的已用结构关键字；哈希遵守 tb-json-v1，不推断任何教学身份。 */
@Component
public class DeliveryContract {
    private final ObjectMapper mapper;
    private final JsonNode schema;
    public record Issue(String code, String fieldPath) {}
    public DeliveryContract(ObjectMapper mapper) {
        this.mapper = mapper.copy().enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
            .enable(com.fasterxml.jackson.databind.DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
        try (var in = getClass().getResourceAsStream("/contracts/backend_candidate_delivery_v1.schema.json");
             var registry = getClass().getResourceAsStream("/contracts/identity-authorities.v1.json")) {
            schema = this.mapper.readTree(in);
            if (this.mapper.readTree(registry).path("contracts").size() != 0) throw new IllegalStateException("production_stable_registry_must_remain_empty");
        } catch (Exception e) { throw new IllegalStateException("delivery_contract_load_failed", e); }
    }
    public JsonNode parse(byte[] raw) {
        try { var parsed=mapper.readTree(raw); if(parsed==null||parsed.isMissingNode()) throw new IllegalArgumentException("empty_json"); return parsed; }
        catch (Exception e) { throw new DeliveryException(400, "delivery_json_invalid_or_duplicate_member"); }
    }
    public List<Issue> validate(JsonNode manifest) {
        var errors = new ArrayList<Issue>(); validateNode(manifest, schema, "", errors);
        if (!errors.isEmpty()) return errors;
        try { canonical(manifest); } catch (DeliveryException e) { errors.add(new Issue(e.getMessage(), "")); return errors; }
        Set<String> fileKeys = unique(manifest.path("files"), "fileKey", "/files", errors);
        Set<String> docKeys = unique(manifest.path("sourceDocuments"), "documentKey", "/sourceDocuments", errors);
        unique(manifest.path("questions"), "itemKey", "/questions", errors);
        var identities = new HashSet<String>(); var media = new HashSet<String>();
        for (var file : manifest.path("files")) {
            media.add(file.path("sha256").asText() + ":" + file.path("mediaType").asText());
            String p = file.path("path").asText();
            if (p.contains("\\") || p.contains(":") || p.indexOf('\0') >= 0
                    || java.util.Arrays.stream(p.split("/", -1)).anyMatch(s -> s.isEmpty() || s.equals(".") || s.equals("..")))
                errors.add(new Issue("package_path_invalid", "/files/" + file.path("fileKey").asText()));
        }
        for (var doc : manifest.path("sourceDocuments")) if (!fileKeys.contains(doc.path("fileKey").asText())) errors.add(new Issue("source_file_unresolved", "/sourceDocuments"));
        for (int i = 0; i < manifest.path("questions").size(); i++) {
            var q = manifest.path("questions").get(i); String p = "/questions/" + i;
            if (!docKeys.contains(q.path("sourceDocumentKey").asText())) errors.add(new Issue("source_document_unresolved", p));
            var identity = q.path("identity");
            if (!identity.path("mode").asText().equals("one_shot_candidate")) errors.add(new Issue("stable_identity_contract_not_registered", p + "/identity"));
            else if (!identities.add(identity.path("candidateId").asText())) errors.add(new Issue("duplicate_question_identity", p + "/identity"));
            for (var key : q.path("sourceEvidence").path("evidenceFileKeys")) if (!fileKeys.contains(key.asText())) errors.add(new Issue("evidence_file_unresolved", p));
            unique(q.path("content").path("media"), "assetKey", p + "/content/media", errors);
            for (var asset : q.path("content").path("media")) if (!media.contains(asset.path("sha256").asText() + ":" + asset.path("mediaType").asText())) errors.add(new Issue("media_manifest_unresolved", p));
            if (!q.path("contentHash").isNull() && !q.path("contentHash").asText().equals(contentHash(q))) errors.add(new Issue("content_hash_mismatch", p + "/contentHash"));
        }
        return errors;
    }
    private Set<String> unique(JsonNode items, String field, String path, List<Issue> errors) {
        Set<String> seen = new HashSet<>(); for (var item : items) if (!seen.add(item.path(field).asText())) errors.add(new Issue("duplicate_" + field, path)); return seen;
    }
    private void validateNode(JsonNode n, JsonNode s, String path, List<Issue> errors) {
        if (n == null) { errors.add(new Issue("schema_invalid", path)); return; }
        if (s.has("$ref")) { validateNode(n, schema.at(s.path("$ref").asText().substring(1)), path, errors); return; }
        if (s.has("oneOf")) {
            int matched = 0; for (var choice : s.path("oneOf")) { var e = new ArrayList<Issue>(); validateNode(n, choice, path, e); if (e.isEmpty()) matched++; }
            if (matched != 1) errors.add(new Issue("schema_oneOf", path)); return;
        }
        if (s.has("type")) {
            boolean good = false; var types = s.path("type");
            if (types.isTextual()) good = isType(n, types.asText()); else for (var t : types) good |= isType(n, t.asText());
            if (!good) { errors.add(new Issue("schema_type", path)); return; }
        }
        if (s.has("const") && !n.equals(s.get("const"))) errors.add(new Issue("schema_const", path));
        if (s.has("enum")) { boolean found = false; for (var v : s.get("enum")) found |= n.equals(v); if (!found) errors.add(new Issue("schema_enum", path)); }
        if (n.isObject()) {
            for (var k : s.path("required")) if (!n.has(k.asText())) errors.add(new Issue("schema_required", path + "/" + k.asText()));
            if (s.has("minProperties") && n.size() < s.path("minProperties").asInt()) errors.add(new Issue("schema_minProperties", path));
            n.fields().forEachRemaining(f -> {
                var child = s.path("properties").get(f.getKey()); var extra = s.get("additionalProperties");
                if (child != null) validateNode(f.getValue(), child, path + "/" + f.getKey(), errors);
                else if (extra != null && extra.isObject()) validateNode(f.getValue(), extra, path + "/" + f.getKey(), errors);
                else if (extra != null && extra.isBoolean() && !extra.asBoolean()) errors.add(new Issue("schema_unknown_field", path + "/" + f.getKey()));
            });
        }
        if (n.isArray()) {
            if (s.has("minItems") && n.size() < s.path("minItems").asInt() || s.has("maxItems") && n.size() > s.path("maxItems").asInt()) errors.add(new Issue("schema_array_size", path));
            if (s.has("items")) for (int i = 0; i < n.size(); i++) validateNode(n.get(i), s.get("items"), path + "/" + i, errors);
        }
        if (n.isTextual()) {
            String text = n.asText(); int length = text.codePointCount(0, text.length());
            if (s.has("minLength") && length < s.path("minLength").asInt() || s.has("maxLength") && length > s.path("maxLength").asInt()) errors.add(new Issue("schema_string_size", path));
            if (s.has("pattern") && !Pattern.compile(s.path("pattern").asText()).matcher(text).find()) errors.add(new Issue("schema_pattern", path));
            if (s.path("format").asText().equals("uuid")) try { UUID.fromString(text); } catch (IllegalArgumentException e) { errors.add(new Issue("schema_uuid", path)); }
        }
        if (n.isNumber() && (s.has("minimum") && n.decimalValue().compareTo(s.get("minimum").decimalValue()) < 0
                || s.has("maximum") && n.decimalValue().compareTo(s.get("maximum").decimalValue()) > 0)) errors.add(new Issue("schema_number_range", path));
    }
    private boolean isType(JsonNode n, String t) {
        return switch (t) { case "object" -> n.isObject(); case "array" -> n.isArray(); case "string" -> n.isTextual(); case "integer" -> n.isIntegralNumber(); case "null" -> n.isNull(); case "boolean" -> n.isBoolean(); default -> false; };
    }
    public byte[] canonical(JsonNode n) {
        StringBuilder out=new StringBuilder(); appendCanonical(ordered(n),out); return out.toString().getBytes(StandardCharsets.UTF_8);
    }
    private void appendCanonical(JsonNode n,StringBuilder out) {
        if(n.isObject()) {
            out.append('{'); var it=n.fields(); boolean first=true;
            while(it.hasNext()) { var f=it.next(); if(!first) out.append(','); first=false; quote(f.getKey(),out); out.append(':'); appendCanonical(f.getValue(),out); }
            out.append('}');
        } else if(n.isArray()) { out.append('['); for(int i=0;i<n.size();i++) { if(i>0) out.append(','); appendCanonical(n.get(i),out); } out.append(']'); }
        else if(n.isTextual()) quote(n.asText(),out); else out.append(n.toString());
    }
    private void quote(String s,StringBuilder out) {
        out.append('"');
        for(int i=0;i<s.length();i++) {
            char c=s.charAt(i);
            switch(c) {
                case '"' -> out.append("\\\""); case '\\' -> out.append("\\\\");
                case '\b' -> out.append("\\b"); case '\t' -> out.append("\\t"); case '\n' -> out.append("\\n");
                case '\f' -> out.append("\\f"); case '\r' -> out.append("\\r");
                default -> { if(c<32) out.append("\\u").append(HexFormat.of().toHexDigits((short)c)); else out.append(c); }
            }
        }
        out.append('"');
    }
    private JsonNode ordered(JsonNode n) {
        if (n.isObject()) {
            ObjectNode result = mapper.createObjectNode(); var keys = new ArrayList<String>(); n.fieldNames().forEachRemaining(keys::add);
            keys.sort((a, b) -> java.util.Arrays.compare(a.codePoints().toArray(), b.codePoints().toArray()));
            for (String k : keys) { validString(k); result.set(k, ordered(n.get(k))); } return result;
        }
        if (n.isArray()) { var result = mapper.createArrayNode(); for (var item : n) result.add(ordered(item)); return result; }
        if (n.isTextual()) validString(n.asText());
        if (n.isNumber() && (!n.isIntegralNumber() || n.bigIntegerValue().abs().compareTo(java.math.BigInteger.valueOf(9007199254740991L)) > 0)) throw new DeliveryException(400, "unsupported_json_number");
        return n;
    }
    private void validString(String s) {
        for (int i = 0; i < s.length(); i++) if (Character.isSurrogate(s.charAt(i))) {
            if (!Character.isHighSurrogate(s.charAt(i)) || i + 1 == s.length() || !Character.isLowSurrogate(s.charAt(++i))) throw new DeliveryException(400, "unicode_surrogate_invalid");
        }
    }
    public String digest(JsonNode n) { return sha256(canonical(n)); }
    public static String sha256(byte[] bytes) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)); } catch (Exception e) { throw new IllegalStateException(e); }
    }
    public String contentHash(JsonNode q) { var e = mapper.createObjectNode(); e.put("hashContract", "tb-content-v1"); e.set("content", q.path("content")); return digest(e); }
    public String requestDigest(JsonNode m) { ObjectNode copy = m.deepCopy(); copy.remove("importRequestId"); var e = mapper.createObjectNode(); e.put("hashContract", "tb-delivery-v1"); e.set("manifest", copy); return digest(e); }
    public String sourceKey(JsonNode m, JsonNode q) {
        var tuple = mapper.createArrayNode().add(m.path("workspaceId").asText()).add(m.path("sourceSystem").asText())
            .add("one_shot_candidate").add(m.path("packageId").asText()).add(q.path("identity").path("candidateId").asText());
        return "g0/one-shot/" + digest(tuple);
    }
}
