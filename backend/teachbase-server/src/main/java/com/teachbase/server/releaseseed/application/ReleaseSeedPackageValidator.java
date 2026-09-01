package com.teachbase.server.releaseseed.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;

/** Java-side structural and byte-level validator for the Release Seed V1 contract. */
@Component
public class ReleaseSeedPackageValidator {

    private static final Pattern SHA256 = Pattern.compile("[0-9a-f]{64}");
    private static final List<String> PAYLOAD_FILES = List.of(
            "questions.jsonl", "question_relations.jsonl", "source_documents.jsonl",
            "source_regions.jsonl", "rejected_questions.jsonl");
    private final ObjectMapper objectMapper;

    public ReleaseSeedPackageValidator(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public ValidatedReleaseSeedPackage validate(Path requestedRoot) {
        try {
            Path root = requestedRoot.toAbsolutePath().normalize();
            if (!Files.isDirectory(root)) throw invalid("release_seed_package_root_missing");
            for (String required : List.of(
                    "manifest.json", "questions.jsonl", "question_relations.jsonl",
                    "source_documents.jsonl", "source_regions.jsonl", "rejected_questions.jsonl",
                    "validation_report.json", "review_report.json")) {
                requireRegular(root, required);
            }
            JsonNode manifest = readObject(root.resolve("manifest.json"), "release_seed_manifest_invalid");
            JsonNode validationReport = readObject(
                    root.resolve("validation_report.json"), "release_seed_validation_report_invalid");
            JsonNode reviewReport = readObject(root.resolve("review_report.json"), "release_seed_review_report_invalid");
            requireText(manifest, "schemaVersion", "release_seed_manifest_schema_missing");
            if (!manifest.path("schemaVersion").asText().equals("teachbase.release-seed.v1")) {
                throw invalid("release_seed_schema_version_unsupported");
            }
            for (String field : List.of(
                    "batchId", "releaseVersion", "contentSha256", "taggerName", "taggerVersion",
                    "taggerInputHash", "reviewedBy", "reviewedAt", "reviewPolicyVersion")) {
                requireText(manifest, field, "release_seed_manifest_field_missing:" + field);
            }
            requireHash(manifest.path("contentSha256").asText(), "release_seed_manifest_hash_invalid");
            requireHash(manifest.path("taggerInputHash").asText(), "release_seed_tagger_hash_invalid");

            List<JsonNode> questions = readJsonLines(root.resolve("questions.jsonl"));
            List<JsonNode> rejected = readJsonLines(root.resolve("rejected_questions.jsonl"));
            List<JsonNode> relations = readJsonLines(root.resolve("question_relations.jsonl"));
            List<JsonNode> sourceDocuments = readJsonLines(root.resolve("source_documents.jsonl"));
            List<JsonNode> sourceRegions = readJsonLines(root.resolve("source_regions.jsonl"));
            if (questions.size() > 500) throw invalid("release_seed_question_limit_exceeded");
            requireCount(manifest, "questionCount", questions.size());
            requireCount(manifest, "approvedQuestionCount", questions.size());
            requireCount(manifest, "rejectedQuestionCount", rejected.size());
            if (manifest.path("pendingReviewQuestionCount").asInt(-1) != 0) {
                throw invalid("release_seed_frozen_package_contains_pending_questions");
            }

            String computedHash = payloadHash(root);
            if (!computedHash.equals(manifest.path("contentSha256").asText())) {
                throw invalid("release_seed_package_hash_mismatch");
            }
            validateReportBinding(manifest, validationReport, true);
            validateReportBinding(manifest, reviewReport, false);

            Map<String, JsonNode> documentsByKey = index(sourceDocuments, "sourceDocumentKey", "source_document");
            Map<String, JsonNode> regionsByKey = index(sourceRegions, "sourceRegionKey", "source_region");
            validateSources(root, sourceDocuments, sourceRegions, documentsByKey);
            validateQuestions(root, questions, documentsByKey, regionsByKey);
            validateRelations(questions, relations);
            validateRejected(rejected);
            return new ValidatedReleaseSeedPackage(
                    root, manifest, validationReport, reviewReport, List.copyOf(questions), List.copyOf(rejected),
                    List.copyOf(relations), List.copyOf(sourceDocuments), List.copyOf(sourceRegions),
                    Map.copyOf(documentsByKey), Map.copyOf(regionsByKey), computedHash);
        } catch (ReleaseSeedValidationException exception) {
            throw exception;
        } catch (IOException exception) {
            throw new ReleaseSeedValidationException("release_seed_package_io_failed", exception);
        }
    }

    private void validateQuestions(
            Path root,
            List<JsonNode> questions,
            Map<String, JsonNode> documents,
            Map<String, JsonNode> regions) throws IOException {
        Set<String> externalKeys = new HashSet<>();
        Set<String> sourceKeys = new HashSet<>();
        for (JsonNode question : questions) {
            if (!question.isObject()) throw invalid("release_seed_question_not_object");
            String externalKey = text(question, "externalKey", "release_seed_external_key_missing");
            String sourceSystem = text(question, "sourceSystem", "release_seed_source_system_missing");
            String sourceKey = text(question, "sourceKey", "release_seed_source_key_missing");
            requireHash(text(question, "contentHash", "release_seed_content_hash_missing"),
                    "release_seed_content_hash_invalid");
            requireHash(text(question, "taggerInputHash", "release_seed_tagger_input_hash_missing"),
                    "release_seed_tagger_input_hash_invalid");
            if (!externalKeys.add(externalKey)) throw invalid("release_seed_external_key_duplicate");
            if (!sourceKeys.add(sourceSystem + "\u0000" + sourceKey)) throw invalid("release_seed_source_key_duplicate");
            JsonNode original = question.path("original");
            if (!original.isObject() || original.path("prompt").asText().isBlank()) {
                throw invalid("release_seed_original_prompt_missing");
            }
            JsonNode review = question.path("review");
            if (!review.isObject() || !review.path("reviewStatus").asText().equals("approved")) {
                throw invalid("release_seed_question_not_human_approved");
            }
            for (String field : List.of("reviewerId", "reviewedAt", "reviewPolicyVersion")) {
                requireText(review, field, "release_seed_question_review_missing:" + field);
            }
            if (!question.path("primaryKnowledgeTag").isTextual()
                    || question.path("primaryKnowledgeTag").asText().isBlank()) {
                throw invalid("release_seed_primary_knowledge_missing");
            }
            if (!question.path("secondaryKnowledgeTags").isArray()) {
                throw invalid("release_seed_secondary_knowledge_invalid");
            }
            int difficulty = question.path("difficultyStars").asInt(0);
            if (difficulty < 1 || difficulty > 5) throw invalid("release_seed_difficulty_invalid");
            String documentKey = question.path("sourceDocumentKey").asText("");
            String regionKey = question.path("sourceRegionKey").asText("");
            if (!documentKey.isBlank() && !documents.containsKey(documentKey)) {
                throw invalid("release_seed_question_source_document_unknown");
            }
            if (!regionKey.isBlank() && !regions.containsKey(regionKey)) {
                throw invalid("release_seed_question_source_region_unknown");
            }
            for (JsonNode image : iterable(original.path("imageRefs"))) {
                validatePortableAsset(root, text(image, "path", "release_seed_image_path_missing"),
                        text(image, "sha256", "release_seed_image_hash_missing"));
            }
        }
    }

    private void validateSources(
            Path root,
            List<JsonNode> sourceDocuments,
            List<JsonNode> sourceRegions,
            Map<String, JsonNode> documentsByKey) throws IOException {
        for (JsonNode document : sourceDocuments) {
            text(document, "sourceSystem", "release_seed_source_document_system_missing");
            String assetPath = text(document, "assetPath", "release_seed_source_asset_path_missing");
            String assetHash = text(document, "assetSha256", "release_seed_source_asset_hash_missing");
            requireHash(text(document, "originalFileSha256", "release_seed_original_file_hash_missing"),
                    "release_seed_original_file_hash_invalid");
            validatePortableAsset(root, assetPath, assetHash);
        }
        for (JsonNode region : sourceRegions) {
            String sourceDocumentKey = text(
                    region, "sourceDocumentKey", "release_seed_region_document_key_missing");
            if (!documentsByKey.containsKey(sourceDocumentKey)) {
                throw invalid("release_seed_region_document_unknown");
            }
            if (!region.path("locator").isObject()) throw invalid("release_seed_region_locator_invalid");
        }
    }

    private void validateRelations(List<JsonNode> questions, List<JsonNode> relations) {
        Set<String> keys = new HashSet<>();
        questions.forEach(question -> keys.add(question.path("externalKey").asText()));
        for (JsonNode relation : relations) {
            if (!keys.contains(relation.path("fromExternalKey").asText())
                    || !keys.contains(relation.path("toExternalKey").asText())) {
                throw invalid("release_seed_relation_question_unknown");
            }
            if (relation.path("relationType").asText().isBlank()) {
                throw invalid("release_seed_relation_type_missing");
            }
            if (!Set.of("child", "variant", "related").contains(relation.path("relationType").asText())) {
                throw invalid("release_seed_relation_type_invalid");
            }
        }
    }

    private void validateRejected(List<JsonNode> rejected) {
        for (JsonNode item : rejected) {
            if (!item.path("reviewStatus").asText().equals("rejected")
                    || !item.path("rejectionReasons").isArray()
                    || item.path("rejectionReasons").isEmpty()) {
                throw invalid("release_seed_rejected_question_invalid");
            }
        }
    }

    private String payloadHash(Path root) throws IOException {
        MessageDigest digest = sha256();
        for (String relative : PAYLOAD_FILES) updateDigest(digest, relative, Files.readAllBytes(root.resolve(relative)));
        Path assets = root.resolve("assets");
        if (Files.exists(assets)) {
            try (var stream = Files.walk(assets)) {
                var files = stream.filter(Files::isRegularFile)
                        .sorted(Comparator.comparing(path -> portable(root.relativize(path))))
                        .toList();
                for (Path file : files) {
                    updateDigest(digest, portable(root.relativize(file)), Files.readAllBytes(file));
                }
            }
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    private void updateDigest(MessageDigest digest, String relative, byte[] bytes) {
        digest.update(relative.getBytes(StandardCharsets.UTF_8));
        digest.update((byte) 0);
        digest.update(bytes);
        digest.update((byte) 0);
    }

    private void validateReportBinding(JsonNode manifest, JsonNode report, boolean validation) {
        String prefix = validation ? "release_seed_validation_report" : "release_seed_review_report";
        if (!report.path("batchId").asText().equals(manifest.path("batchId").asText())
                || !report.path("releaseVersion").asText().equals(manifest.path("releaseVersion").asText())
                || !report.path("packageContentSha256").asText().equals(manifest.path("contentSha256").asText())) {
            throw invalid(prefix + "_binding_mismatch");
        }
        if (validation && (!report.path("passed").asBoolean(false) || report.path("errorCount").asInt(-1) != 0)) {
            throw invalid("release_seed_validation_report_not_passed");
        }
        if (!validation) {
            for (String field : List.of("reviewerId", "reviewedAt", "reviewPolicyVersion")) {
                String manifestField = field.equals("reviewerId") ? "reviewedBy" : field;
                if (!report.path(field).asText().equals(manifest.path(manifestField).asText())) {
                    throw invalid("release_seed_review_report_identity_mismatch");
                }
            }
            requireCount(report, "approvedQuestionCount", manifest.path("approvedQuestionCount").asInt());
            requireCount(report, "rejectedQuestionCount", manifest.path("rejectedQuestionCount").asInt());
        }
    }

    private Map<String, JsonNode> index(List<JsonNode> values, String key, String type) {
        Map<String, JsonNode> result = new LinkedHashMap<>();
        for (JsonNode value : values) {
            String id = text(value, key, "release_seed_" + type + "_key_missing");
            if (result.putIfAbsent(id, value) != null) throw invalid("release_seed_" + type + "_key_duplicate");
        }
        return result;
    }

    private List<JsonNode> readJsonLines(Path path) throws IOException {
        String content = decodeUtf8(Files.readAllBytes(path));
        List<JsonNode> result = new ArrayList<>();
        int lineNo = 0;
        for (String line : content.split("\\R", -1)) {
            lineNo++;
            if (line.isBlank()) continue;
            try {
                JsonNode value = objectMapper.readTree(line);
                if (!value.isObject()) throw invalid("release_seed_jsonl_row_not_object:" + path.getFileName());
                result.add(value);
            } catch (JsonProcessingException exception) {
                throw new ReleaseSeedValidationException(
                        "release_seed_jsonl_invalid:" + path.getFileName() + ":" + lineNo, exception);
            }
        }
        return result;
    }

    private JsonNode readObject(Path path, String code) throws IOException {
        try {
            JsonNode value = objectMapper.readTree(decodeUtf8(Files.readAllBytes(path)));
            if (!value.isObject()) throw invalid(code);
            return value;
        } catch (JsonProcessingException exception) {
            throw new ReleaseSeedValidationException(code, exception);
        }
    }

    private String decodeUtf8(byte[] bytes) {
        try {
            var decoder = StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT);
            return decoder.decode(ByteBuffer.wrap(bytes)).toString();
        } catch (java.nio.charset.CharacterCodingException exception) {
            throw new ReleaseSeedValidationException("release_seed_utf8_invalid", exception);
        }
    }

    private void validatePortableAsset(Path root, String relative, String declaredHash) throws IOException {
        requireHash(declaredHash, "release_seed_asset_hash_invalid");
        if (!relative.startsWith("assets/") || relative.contains("\\") || relative.contains(":")
                || relative.split("/").length == 0 || List.of(relative.split("/")).contains("..")) {
            throw invalid("release_seed_asset_path_not_portable");
        }
        Path target = root.resolve(relative).normalize();
        if (!target.startsWith(root) || !Files.isRegularFile(target)) throw invalid("release_seed_asset_missing");
        String actual = HexFormat.of().formatHex(sha256().digest(Files.readAllBytes(target)));
        if (!actual.equals(declaredHash)) throw invalid("release_seed_asset_hash_mismatch");
    }

    private void requireRegular(Path root, String relative) {
        Path path = root.resolve(relative).normalize();
        if (!path.startsWith(root) || !Files.isRegularFile(path)) {
            throw invalid("release_seed_required_file_missing:" + relative);
        }
    }

    private void requireCount(JsonNode value, String field, int expected) {
        if (!value.path(field).isIntegralNumber() || value.path(field).asInt() != expected) {
            throw invalid("release_seed_count_mismatch:" + field);
        }
    }

    private String text(JsonNode node, String field, String code) {
        requireText(node, field, code);
        return node.path(field).asText();
    }

    private void requireText(JsonNode node, String field, String code) {
        if (!node.path(field).isTextual() || node.path(field).asText().isBlank()) throw invalid(code);
    }

    private void requireHash(String value, String code) {
        if (!SHA256.matcher(value).matches()) throw invalid(code);
    }

    private Iterable<JsonNode> iterable(JsonNode value) {
        return value != null && value.isArray() ? value : List.of();
    }

    private String portable(Path path) {
        return path.toString().replace('\\', '/');
    }

    private MessageDigest sha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("sha256_unavailable", exception);
        }
    }

    private ReleaseSeedValidationException invalid(String code) {
        return new ReleaseSeedValidationException(code);
    }
}
