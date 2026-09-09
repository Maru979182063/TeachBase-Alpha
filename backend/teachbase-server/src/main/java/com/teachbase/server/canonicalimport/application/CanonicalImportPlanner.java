package com.teachbase.server.canonicalimport.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.teachbase.server.fileasset.api.FileVersionDirectory;
import com.teachbase.server.question.api.QuestionHashPreviewer;
import com.teachbase.server.taxonomy.api.ResolveTaxonomyNodeRequest;
import com.teachbase.server.taxonomy.api.TaxonomyCatalog;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.UUID;
import org.springframework.stereotype.Component;

/**
 * 中文维护说明：Validate 阶段一次性完成 schema、稳定 key、引用和 DAG 校验；
 * 执行阶段只消费冻结 plan，禁止靠数据库插入失败来发现依赖。
 */
@Component
public class CanonicalImportPlanner {

    public static final String CONTRACT = "teachbase.canonical-content-import.v1";
    private final ObjectMapper objectMapper;
    private final FileVersionDirectory files;
    private final QuestionHashPreviewer questions;
    private final TaxonomyCatalog taxonomies;

    public CanonicalImportPlanner(
            ObjectMapper objectMapper,
            FileVersionDirectory files,
            QuestionHashPreviewer questions,
            TaxonomyCatalog taxonomies) {
        this.objectMapper = objectMapper;
        this.files = files;
        this.questions = questions;
        this.taxonomies = taxonomies;
    }

    public CanonicalImportPlan plan(UUID workspaceId, UUID actorUserId, JsonNode requested, String declaredHash) {
        if (requested == null || !requested.isObject()) invalid("canonical_import_package_object_required");
        JsonNode canonical = canonicalize(requested);
        String contract = text(canonical, "contractVersion");
        if (!CONTRACT.equals(contract)) invalid("canonical_import_contract_version_unsupported");
        JsonNode identity = object(canonical, "importRequest");
        String packageKey = bounded(text(identity, "packageKey"), 240, "canonical_import_package_key_invalid");
        String producer = bounded(text(identity, "producer"), 160, "canonical_import_producer_invalid");
        String packageHash = hash(canonical);
        if (declaredHash != null && !declaredHash.isBlank()
                && !packageHash.equals(declaredHash.trim().toLowerCase(java.util.Locale.ROOT))) {
            invalid("canonical_import_package_hash_mismatch");
        }

        ArrayNode fileValues = array(canonical, "fileReferences");
        ArrayNode documentValues = array(canonical, "sourceDocuments");
        ArrayNode regionValues = array(canonical, "sourceRegions");
        ArrayNode questionValues = array(canonical, "questions");
        ArrayNode moduleValues = array(canonical, "standardModules");
        ArrayNode taxonomyValues = array(canonical, "taxonomyAssignments");
        ArrayNode reviewValues = array(canonical, "reviewIntents");
        JsonNode handout = object(canonical, "handout");
        object(canonical, "lineage");
        object(canonical, "producerMetadata");

        Map<String, JsonNode> fileByKey = index(fileValues, "fileKey", "file");
        Map<String, JsonNode> documentByKey = index(documentValues, "sourceDocumentKey", "source_document");
        Map<String, JsonNode> regionByKey = index(regionValues, "sourceRegionKey", "source_region");
        Map<String, JsonNode> questionByKey = index(questionValues, "questionKey", "question");
        Map<String, JsonNode> moduleByKey = index(moduleValues, "moduleKey", "standard_module");
        validateFileReferences(workspaceId, fileByKey);

        List<PlannedImportOperation> operations = new ArrayList<>();
        for (var entry : fileByKey.entrySet()) add(operations, "file:" + entry.getKey(), "file_reference", List.of(), entry.getValue());
        for (var entry : documentByKey.entrySet()) {
            String fileKey = text(entry.getValue(), "fileKey");
            requireKey(fileByKey, fileKey, "canonical_import_source_file_unknown");
            add(operations, "source-document:" + entry.getKey(), "source_document", List.of("file:" + fileKey), entry.getValue());
        }
        for (var entry : regionByKey.entrySet()) {
            String documentKey = text(entry.getValue(), "sourceDocumentKey");
            requireKey(documentByKey, documentKey, "canonical_import_region_document_unknown");
            add(operations, "source-region:" + entry.getKey(), "source_region",
                    List.of("source-document:" + documentKey), entry.getValue());
        }
        for (var entry : questionByKey.entrySet()) {
            JsonNode value = entry.getValue();
            questions.previewHashes(CanonicalImportPayloadMapper.question(value));
            ArrayNode sources = requiredNonEmptyArray(value, "sources", "canonical_import_question_provenance_required");
            add(operations, "question:" + entry.getKey(), "question_revision", List.of(), value);
            for (JsonNode source : sources) {
                List<String> dependencies = sourceDependencies(source, documentByKey, regionByKey);
                dependencies.addFirst("question:" + entry.getKey());
                add(operations, "question-source:" + entry.getKey() + ":" + text(source, "evidenceKey"),
                        "question_provenance", dependencies, provenancePayload("questionKey", entry.getKey(), source));
            }
        }
        for (var entry : moduleByKey.entrySet()) {
            JsonNode value = entry.getValue();
            text(value, "moduleType"); text(value, "title"); text(value, "subject");
            if (!object(value, "content").isObject()) invalid("canonical_import_module_content_invalid");
            ArrayNode sources = requiredNonEmptyArray(value, "sources", "canonical_import_module_provenance_required");
            add(operations, "module:" + entry.getKey(), "standard_module_revision", List.of(), value);
            for (JsonNode source : sources) {
                List<String> dependencies = sourceDependencies(source, documentByKey, regionByKey);
                dependencies.addFirst("module:" + entry.getKey());
                add(operations, "module-source:" + entry.getKey() + ":" + text(source, "evidenceKey"),
                        "standard_module_provenance", dependencies, provenancePayload("moduleKey", entry.getKey(), source));
            }
            for (JsonNode reference : optionalArray(value, "files")) {
                String fileKey = text(reference, "fileKey");
                requireKey(fileByKey, fileKey, "canonical_import_module_file_unknown");
                ObjectNode payload = reference.deepCopy(); payload.put("moduleKey", entry.getKey());
                add(operations, "module-file:" + entry.getKey() + ":" + text(reference, "referenceKey"),
                        "standard_module_file", List.of("module:" + entry.getKey(), "file:" + fileKey), payload);
            }
        }
        planTaxonomy(workspaceId, actorUserId, taxonomyValues, questionByKey, moduleByKey, operations);
        planReviews(reviewValues, questionByKey, moduleByKey, operations);
        planHandout(handout, fileByKey, documentByKey, regionByKey, questionByKey, moduleByKey, operations);
        return new CanonicalImportPlan(contract, producer, packageKey, packageHash, canonical, List.copyOf(operations));
    }

    private void validateFileReferences(UUID workspaceId, Map<String, JsonNode> fileByKey) {
        List<UUID> ids = fileByKey.values().stream().map(value -> uuid(value, "fileVersionId")).toList();
        var found = files.findAll(workspaceId, ids);
        Map<UUID, String> hashes = new HashMap<>();
        found.forEach(value -> hashes.put(value.fileVersionId(), value.sha256()));
        for (JsonNode value : fileByKey.values()) {
            UUID id = uuid(value, "fileVersionId");
            if (!hashes.containsKey(id)) invalid("canonical_import_file_version_not_found");
            String declared = text(value, "sha256").toLowerCase(java.util.Locale.ROOT);
            if (!declared.equals(hashes.get(id))) invalid("canonical_import_file_hash_mismatch");
        }
    }

    private void planTaxonomy(
            UUID workspaceId, UUID actorUserId, ArrayNode values,
            Map<String, JsonNode> questionsByKey, Map<String, JsonNode> modulesByKey,
            List<PlannedImportOperation> operations) {
        Set<String> keys = new HashSet<>();
        for (JsonNode value : values) {
            String assignmentKey = text(value, "assignmentKey");
            if (!keys.add(assignmentKey)) invalid("canonical_import_taxonomy_assignment_duplicate");
            String targetType = text(value, "targetType");
            String targetKey = text(value, "targetKey");
            String dependency;
            if (targetType.equals("question")) {
                requireKey(questionsByKey, targetKey, "canonical_import_taxonomy_question_unknown");
                dependency = "question:" + targetKey;
            } else if (targetType.equals("standard_module")) {
                requireKey(modulesByKey, targetKey, "canonical_import_taxonomy_module_unknown");
                dependency = "module:" + targetKey;
            } else {
                throw new CanonicalImportValidationException("canonical_import_taxonomy_target_invalid");
            }
            taxonomies.resolve(new ResolveTaxonomyNodeRequest(
                    workspaceId, actorUserId, uuid(value, "taxonomyVersionId"), text(value, "codeOrAlias")));
            add(operations, "taxonomy:" + assignmentKey, "taxonomy_assignment", List.of(dependency), value);
        }
    }

    private void planReviews(
            ArrayNode values, Map<String, JsonNode> questionsByKey, Map<String, JsonNode> modulesByKey,
            List<PlannedImportOperation> operations) {
        Set<String> keys = new HashSet<>();
        for (JsonNode value : values) {
            String intentKey = text(value, "intentKey");
            if (!keys.add(intentKey)) invalid("canonical_import_review_intent_duplicate");
            String type = text(value, "targetType");
            String target = text(value, "targetKey");
            String dependency;
            if (type.equals("question")) {
                requireKey(questionsByKey, target, "canonical_import_review_question_unknown");
                dependency = "question:" + target;
            } else if (type.equals("standard_module")) {
                requireKey(modulesByKey, target, "canonical_import_review_module_unknown");
                dependency = "module:" + target;
            } else {
                throw new CanonicalImportValidationException("canonical_import_review_target_invalid");
            }
            add(operations, "review:" + intentKey, "review_intent", List.of(dependency), value);
        }
    }

    private void planHandout(
            JsonNode handout, Map<String, JsonNode> files, Map<String, JsonNode> documents,
            Map<String, JsonNode> regions, Map<String, JsonNode> questions, Map<String, JsonNode> modules,
            List<PlannedImportOperation> operations) {
        String editorKey = text(handout, "editorDocumentKey");
        object(handout, "masterDoc");
        ArrayNode overrides = array(handout, "versionOverrides");
        if (overrides.size() != 3) invalid("canonical_import_editor_overrides_invalid");
        add(operations, "editor:" + editorKey, "editor_revision", List.of(), handout);
        ArrayNode editions = array(handout, "editions");
        if (editions.isEmpty()) invalid("canonical_import_handout_editions_required");
        int canonicalCount = 0;
        Set<String> editionKeys = new HashSet<>();
        Set<String> teacherOccurrenceKeys = new HashSet<>();
        Map<String, Integer> coveredRegions = new HashMap<>();
        Set<String> dependencies = new LinkedHashSet<>();
        dependencies.add("editor:" + editorKey);
        for (JsonNode edition : editions) {
            String editionKey = text(edition, "editionKey");
            if (!editionKeys.add(editionKey)) invalid("canonical_import_edition_key_duplicate");
            String role = text(edition, "editionRole");
            if (role.equals("canonical")) canonicalCount++;
            else if (!role.equals("projection")) invalid("canonical_import_edition_role_invalid");
            ArrayNode occurrences = array(edition, "occurrences");
            Map<String, JsonNode> occurrenceByKey = index(occurrences, "occurrenceKey", "occurrence:" + editionKey);
            for (var occurrenceEntry : occurrenceByKey.entrySet()) {
                JsonNode occurrence = occurrenceEntry.getValue();
                String parent = optionalText(occurrence, "parentOccurrenceKey");
                if (parent != null && !occurrenceByKey.containsKey(parent)) invalid("canonical_import_occurrence_parent_unknown");
                String kind = text(occurrence, "kind");
                if (role.equals("canonical")) teacherOccurrenceKeys.add(occurrenceEntry.getKey());
                if (kind.equals("question")) {
                    String key = text(occurrence, "questionKey");
                    requireKey(questions, key, "canonical_import_occurrence_question_unknown");
                    dependencies.add("question:" + key);
                } else if (kind.equals("standard_module")) {
                    String key = text(occurrence, "moduleKey");
                    requireKey(modules, key, "canonical_import_occurrence_module_unknown");
                    dependencies.add("module:" + key);
                } else if (kind.equals("ordinary_content")) {
                    object(occurrence, "localContent");
                } else if (!kind.equals("container")) invalid("canonical_import_occurrence_kind_invalid");
                for (JsonNode source : optionalArray(occurrence, "sources")) {
                    String documentKey = text(source, "sourceDocumentKey");
                    requireKey(documents, documentKey, "canonical_import_occurrence_document_unknown");
                    dependencies.add("source-document:" + documentKey);
                    String regionKey = optionalText(source, "sourceRegionKey");
                    if (regionKey != null) {
                        requireKey(regions, regionKey, "canonical_import_occurrence_region_unknown");
                        if (!documentKey.equals(text(regions.get(regionKey), "sourceDocumentKey"))) {
                            invalid("canonical_import_occurrence_region_document_mismatch");
                        }
                        dependencies.add("source-region:" + regionKey);
                        coveredRegions.merge(regionKey, 1, Integer::sum);
                    }
                }
            }
            assertAcyclic(occurrenceByKey);
        }
        if (canonicalCount != 1) invalid("canonical_import_one_canonical_edition_required");
        for (JsonNode edition : editions) {
            if (!"projection".equals(edition.path("editionRole").asText())) continue;
            String teacherKey = text(edition, "canonicalTeacherEditionKey");
            JsonNode teacher = null;
            for (JsonNode candidate : editions) {
                if (teacherKey.equals(candidate.path("editionKey").asText())
                        && "canonical".equals(candidate.path("editionRole").asText())) teacher = candidate;
            }
            if (teacher == null) invalid("canonical_import_projection_teacher_unknown");
            for (JsonNode delta : optionalArray(edition.path("delta"), "operations")) {
                if (!teacherOccurrenceKeys.contains(text(delta, "occurrenceKey"))) {
                    invalid("canonical_import_projection_delta_occurrence_unknown");
                }
            }
        }
        for (var entry : regions.entrySet()) {
            if (entry.getValue().path("coverageRequired").asBoolean(false)
                    && coveredRegions.getOrDefault(entry.getKey(), 0) != 1) {
                invalid("canonical_import_placement_provenance_coverage_invalid:" + entry.getKey());
            }
        }
        for (JsonNode artifact : array(handout, "artifacts")) {
            String fileKey = text(artifact, "fileKey");
            requireKey(files, fileKey, "canonical_import_artifact_file_unknown");
            dependencies.add("file:" + fileKey);
            String sourceDocumentKey = optionalText(artifact, "sourceDocumentKey");
            if (sourceDocumentKey != null) {
                requireKey(documents, sourceDocumentKey, "canonical_import_artifact_document_unknown");
                dependencies.add("source-document:" + sourceDocumentKey);
            }
        }
        add(operations, "handout:" + editorKey, "handout_composition", List.copyOf(dependencies), handout);
    }

    private List<String> sourceDependencies(
            JsonNode source, Map<String, JsonNode> documents, Map<String, JsonNode> regions) {
        List<String> result = new java.util.LinkedList<>();
        String documentKey = text(source, "sourceDocumentKey");
        requireKey(documents, documentKey, "canonical_import_provenance_document_unknown");
        result.add("source-document:" + documentKey);
        String regionKey = optionalText(source, "sourceRegionKey");
        if (regionKey != null) {
            requireKey(regions, regionKey, "canonical_import_provenance_region_unknown");
            if (!documentKey.equals(text(regions.get(regionKey), "sourceDocumentKey"))) {
                invalid("canonical_import_provenance_region_document_mismatch");
            }
            result.add("source-region:" + regionKey);
        }
        text(source, "evidenceKey");
        return result;
    }

    private void assertAcyclic(Map<String, JsonNode> occurrences) {
        for (String start : occurrences.keySet()) {
            Set<String> visited = new HashSet<>();
            String current = start;
            while (current != null) {
                if (!visited.add(current)) invalid("canonical_import_occurrence_cycle");
                current = optionalText(occurrences.get(current), "parentOccurrenceKey");
            }
        }
    }

    private ObjectNode provenancePayload(String targetField, String targetKey, JsonNode source) {
        ObjectNode result = source.deepCopy(); result.put(targetField, targetKey); return result;
    }

    private void add(
            List<PlannedImportOperation> operations, String key, String type,
            List<String> dependencies, JsonNode payload) {
        if (operations.stream().anyMatch(value -> value.operationKey().equals(key))) {
            invalid("canonical_import_operation_key_duplicate:" + key);
        }
        JsonNode canonical = canonicalize(payload);
        operations.add(new PlannedImportOperation(
                key, type, operations.size(), List.copyOf(dependencies), canonical, hash(canonical)));
    }

    private Map<String, JsonNode> index(ArrayNode values, String keyField, String type) {
        Map<String, JsonNode> result = new LinkedHashMap<>();
        for (JsonNode value : values) {
            if (!value.isObject()) invalid("canonical_import_item_object_required:" + type);
            String key = text(value, keyField);
            if (result.putIfAbsent(key, value) != null) invalid("canonical_import_stable_key_duplicate:" + type);
        }
        return result;
    }

    private void requireKey(Map<String, JsonNode> values, String key, String code) {
        if (!values.containsKey(key)) invalid(code);
    }

    private ArrayNode array(JsonNode value, String field) {
        JsonNode result = value.get(field);
        if (result == null || !result.isArray()) invalid("canonical_import_array_required:" + field);
        return (ArrayNode) result;
    }

    private ArrayNode optionalArray(JsonNode value, String field) {
        JsonNode result = value == null ? null : value.get(field);
        if (result == null || result.isNull()) return objectMapper.createArrayNode();
        if (!result.isArray()) invalid("canonical_import_array_required:" + field);
        return (ArrayNode) result;
    }

    private ArrayNode requiredNonEmptyArray(JsonNode value, String field, String code) {
        ArrayNode result = optionalArray(value, field);
        if (result.isEmpty()) invalid(code);
        return result;
    }

    private JsonNode object(JsonNode value, String field) {
        JsonNode result = value.get(field);
        if (result == null || !result.isObject()) invalid("canonical_import_object_required:" + field);
        return result;
    }

    private String text(JsonNode value, String field) {
        String result = value.path(field).asText("").trim();
        if (result.isEmpty()) invalid("canonical_import_field_required:" + field);
        return result;
    }

    private String optionalText(JsonNode value, String field) {
        String result = value.path(field).asText("").trim();
        return result.isEmpty() ? null : result;
    }

    private UUID uuid(JsonNode value, String field) {
        try {
            return UUID.fromString(text(value, field));
        } catch (IllegalArgumentException exception) {
            throw new CanonicalImportValidationException("canonical_import_uuid_invalid:" + field);
        }
    }

    private String bounded(String value, int max, String code) {
        if (value.length() > max) invalid(code);
        return value;
    }

    private JsonNode canonicalize(JsonNode node) {
        if (node.isObject()) {
            ObjectNode result = objectMapper.createObjectNode();
            Map<String, JsonNode> fields = new TreeMap<>();
            Iterator<Map.Entry<String, JsonNode>> iterator = node.fields();
            iterator.forEachRemaining(entry -> fields.put(entry.getKey(), entry.getValue()));
            fields.forEach((key, value) -> result.set(key, canonicalize(value)));
            return result;
        }
        if (node.isArray()) {
            ArrayNode result = objectMapper.createArrayNode();
            node.forEach(item -> result.add(canonicalize(item)));
            return result;
        }
        return node.deepCopy();
    }

    private String hash(JsonNode value) {
        try {
            return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(
                    objectMapper.writeValueAsString(value).getBytes(StandardCharsets.UTF_8)));
        } catch (JsonProcessingException exception) {
            throw new CanonicalImportValidationException("canonical_import_json_not_serializable");
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("sha256_unavailable", exception);
        }
    }

    private void invalid(String code) {
        throw new CanonicalImportValidationException(code);
    }
}
