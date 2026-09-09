package com.teachbase.server.handout.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import com.teachbase.server.editor.api.EditorRevisionDirectory;
import com.teachbase.server.handout.api.CreateHandoutCompositionRequest;
import com.teachbase.server.handout.api.HandoutCompositionResponse;
import com.teachbase.server.handout.api.HandoutCompositionImporter;
import com.teachbase.server.handout.api.HandoutEditionInput;
import com.teachbase.server.handout.api.HandoutOccurrenceInput;
import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import com.teachbase.server.question.api.QuestionRevisionDescriptor;
import com.teachbase.server.question.api.QuestionRevisionDirectory;
import com.teachbase.server.standardmodule.api.StandardModuleRevisionDescriptor;
import com.teachbase.server.standardmodule.api.StandardModuleRevisionDirectory;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 中文维护说明：将前端或受控迁移提交的 composition 校验为精确 revision 引用；
 * 本服务不创建题目、模块或 editor revision，也不会修改 WP-01 working draft。
 */
@Service
public class HandoutCompositionService implements HandoutCompositionImporter {

    private static final Set<String> KINDS = Set.of(
            "container", "question", "standard_module", "ordinary_content");

    private final WorkspaceDirectory workspaces;
    private final EditorRevisionDirectory editorRevisions;
    private final QuestionRevisionDirectory questions;
    private final StandardModuleRevisionDirectory standardModules;
    private final HandoutCompositionRepository compositions;
    private final AuditTrail auditTrail;
    private final ObjectMapper objectMapper;

    public HandoutCompositionService(
            WorkspaceDirectory workspaces,
            EditorRevisionDirectory editorRevisions,
            QuestionRevisionDirectory questions,
            StandardModuleRevisionDirectory standardModules,
            HandoutCompositionRepository compositions,
            AuditTrail auditTrail,
            ObjectMapper objectMapper) {
        this.workspaces = workspaces;
        this.editorRevisions = editorRevisions;
        this.questions = questions;
        this.standardModules = standardModules;
        this.compositions = compositions;
        this.auditTrail = auditTrail;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public HandoutCompositionResponse create(
            UUID editorDocumentId, UUID editorRevisionId, CreateHandoutCompositionRequest request) {
        validateActor(request.workspaceId(), request.actorUserId());
        editorRevisions.find(request.workspaceId(), editorDocumentId, editorRevisionId)
                .orElseThrow(() -> new HandoutValidationException("handout_editor_revision_not_found"));
        validateArtifacts(request);
        List<ResolvedHandoutEdition> resolved = resolveEditions(request);
        var response = compositions.create(
                request.workspaceId(), request.actorUserId(), editorDocumentId, editorRevisionId,
                resolved, request.artifacts());
        int occurrences = response.editions().stream().mapToInt(value -> value.occurrenceCount()).sum();
        auditTrail.record(new AuditCommand(
                request.workspaceId(), request.actorUserId(), "handout.composition_created",
                "editor_revision", editorRevisionId,
                Map.of("editorDocumentId", editorDocumentId.toString(),
                        "editionCount", response.editions().size(), "occurrenceCount", occurrences,
                        "artifactCount", response.artifactCount())));
        return response;
    }

    @Override
    public HandoutCompositionResponse importComposition(
            UUID editorDocumentId, UUID editorRevisionId, CreateHandoutCompositionRequest request) {
        return create(editorDocumentId, editorRevisionId, request);
    }

    private List<ResolvedHandoutEdition> resolveEditions(CreateHandoutCompositionRequest request) {
        Map<String, HandoutEditionInput> byEdition = new LinkedHashMap<>();
        int canonicalCount = 0;
        for (HandoutEditionInput edition : request.editions()) {
            String key = clean(edition.editionKey());
            if (byEdition.putIfAbsent(key, edition) != null) {
                throw new HandoutValidationException("handout_edition_key_duplicate");
            }
            if (clean(edition.editionRole()).equals("canonical")) canonicalCount++;
        }
        if (canonicalCount != 1) throw new HandoutValidationException("handout_one_canonical_edition_required");

        Set<UUID> questionRevisionIds = new HashSet<>();
        Set<UUID> moduleRevisionIds = new HashSet<>();
        for (HandoutEditionInput edition : request.editions()) {
            validateEditionShape(edition, byEdition);
            for (HandoutOccurrenceInput occurrence : edition.occurrences()) {
                if (occurrence.questionRevisionId() != null) questionRevisionIds.add(occurrence.questionRevisionId());
                if (occurrence.standardModuleRevisionId() != null) {
                    moduleRevisionIds.add(occurrence.standardModuleRevisionId());
                }
            }
        }
        Map<UUID, QuestionRevisionDescriptor> questionByRevision = new HashMap<>();
        for (var value : questions.findAll(request.workspaceId(), List.copyOf(questionRevisionIds))) {
            questionByRevision.put(value.questionRevisionId(), value);
        }
        Map<UUID, StandardModuleRevisionDescriptor> moduleByRevision = new HashMap<>();
        for (var value : standardModules.findAll(request.workspaceId(), List.copyOf(moduleRevisionIds))) {
            moduleByRevision.put(value.standardModuleRevisionId(), value);
        }
        if (questionByRevision.size() != questionRevisionIds.size()) {
            throw new HandoutValidationException("handout_question_revision_not_found");
        }
        if (moduleByRevision.size() != moduleRevisionIds.size()) {
            throw new HandoutValidationException("handout_standard_module_revision_not_found");
        }

        List<ResolvedHandoutEdition> result = new ArrayList<>();
        for (HandoutEditionInput edition : request.editions()) {
            List<ResolvedHandoutOccurrence> occurrences = new ArrayList<>();
            for (HandoutOccurrenceInput occurrence : edition.occurrences()) {
                QuestionRevisionDescriptor question = occurrence.questionRevisionId() == null
                        ? null : questionByRevision.get(occurrence.questionRevisionId());
                StandardModuleRevisionDescriptor module = occurrence.standardModuleRevisionId() == null
                        ? null : moduleByRevision.get(occurrence.standardModuleRevisionId());
                occurrences.add(new ResolvedHandoutOccurrence(
                        clean(occurrence.occurrenceKey()), cleanNullable(occurrence.parentOccurrenceKey()),
                        occurrence.positionIndex(), clean(occurrence.kind()),
                        question == null ? null : question.questionId(), occurrence.questionRevisionId(),
                        module == null ? null : module.standardModuleId(), occurrence.standardModuleRevisionId(),
                        jsonPresent(occurrence.localContent()) ? canonicalize(occurrence.localContent()) : null,
                        canonicalize(occurrence.attributes()), List.copyOf(occurrence.sources())));
            }
            JsonNode rules = canonicalize(edition.projectionRules());
            JsonNode delta = canonicalize(edition.delta());
            var normalized = new ResolvedHandoutEdition(
                    clean(edition.editionKey()), clean(edition.editionRole()),
                    cleanNullable(edition.canonicalTeacherEditionKey()), edition.schemaVersion(),
                    rules, delta, "", List.copyOf(occurrences));
            result.add(new ResolvedHandoutEdition(
                    normalized.editionKey(), normalized.editionRole(), normalized.canonicalTeacherEditionKey(),
                    normalized.schemaVersion(), rules, delta, hash(normalized), normalized.occurrences()));
        }
        // 仓储先写 canonical，再写 projection，确保 self-reference 在同一事务中可解析。
        return result.stream().sorted((left, right) ->
                left.editionRole().equals(right.editionRole()) ? 0
                        : left.editionRole().equals("canonical") ? -1 : 1).toList();
    }

    private void validateEditionShape(HandoutEditionInput edition, Map<String, HandoutEditionInput> editions) {
        String role = clean(edition.editionRole());
        if (!Set.of("canonical", "projection").contains(role)) {
            throw new HandoutValidationException("handout_edition_role_invalid");
        }
        if (edition.schemaVersion() <= 0 || !edition.projectionRules().isObject() || !edition.delta().isObject()) {
            throw new HandoutValidationException("handout_edition_payload_invalid");
        }
        String teacherKey = cleanNullable(edition.canonicalTeacherEditionKey());
        if (role.equals("canonical") && teacherKey != null) {
            throw new HandoutValidationException("handout_canonical_teacher_reference_forbidden");
        }
        if (role.equals("projection")) {
            HandoutEditionInput teacher = teacherKey == null ? null : editions.get(teacherKey);
            if (teacher == null || !clean(teacher.editionRole()).equals("canonical")) {
                throw new HandoutValidationException("handout_projection_teacher_reference_invalid");
            }
        }
        Map<String, HandoutOccurrenceInput> occurrences = new LinkedHashMap<>();
        for (HandoutOccurrenceInput occurrence : edition.occurrences()) {
            String key = clean(occurrence.occurrenceKey());
            if (occurrences.putIfAbsent(key, occurrence) != null) {
                throw new HandoutValidationException("handout_occurrence_key_duplicate");
            }
            validateOccurrenceTarget(occurrence);
            if (!occurrence.attributes().isObject()) {
                throw new HandoutValidationException("handout_occurrence_attributes_invalid");
            }
            for (var source : occurrence.sources()) {
                if (!source.sourceReference().isObject()) {
                    throw new HandoutValidationException("handout_occurrence_source_reference_invalid");
                }
            }
        }
        for (HandoutOccurrenceInput occurrence : edition.occurrences()) {
            String parent = cleanNullable(occurrence.parentOccurrenceKey());
            if (parent != null && !occurrences.containsKey(parent)) {
                throw new HandoutValidationException("handout_occurrence_parent_not_found");
            }
            ensureAcyclic(clean(occurrence.occurrenceKey()), occurrences);
        }
    }

    private void validateOccurrenceTarget(HandoutOccurrenceInput value) {
        String kind = clean(value.kind());
        if (!KINDS.contains(kind)) throw new HandoutValidationException("handout_occurrence_kind_invalid");
        boolean question = value.questionRevisionId() != null;
        boolean module = value.standardModuleRevisionId() != null;
        boolean local = jsonPresent(value.localContent());
        if ((kind.equals("question") && (!question || module || local))
                || (kind.equals("standard_module") && (!module || question || local))
                || (kind.equals("ordinary_content") && (!local || question || module || !value.localContent().isObject()))
                || (kind.equals("container") && (question || module || local))) {
            throw new HandoutValidationException("handout_occurrence_target_invalid");
        }
    }

    private boolean jsonPresent(JsonNode value) {
        return value != null && !value.isNull() && !value.isMissingNode();
    }

    private void ensureAcyclic(String start, Map<String, HandoutOccurrenceInput> occurrences) {
        Set<String> visited = new HashSet<>();
        String current = start;
        while (current != null) {
            if (!visited.add(current)) throw new HandoutValidationException("handout_occurrence_cycle");
            current = cleanNullable(occurrences.get(current).parentOccurrenceKey());
        }
    }

    private void validateArtifacts(CreateHandoutCompositionRequest request) {
        Set<String> keys = new HashSet<>();
        for (var artifact : request.artifacts()) {
            if (!keys.add(clean(artifact.artifactKey()))) {
                throw new HandoutValidationException("handout_artifact_key_duplicate");
            }
            if (!artifact.metadata().isObject()) {
                throw new HandoutValidationException("handout_artifact_metadata_invalid");
            }
        }
    }

    private String hash(ResolvedHandoutEdition edition) {
        ObjectNode root = objectMapper.createObjectNode();
        root.put("editionKey", edition.editionKey());
        root.put("editionRole", edition.editionRole());
        if (edition.canonicalTeacherEditionKey() != null) {
            root.put("canonicalTeacherEditionKey", edition.canonicalTeacherEditionKey());
        }
        root.put("schemaVersion", edition.schemaVersion());
        root.set("projectionRules", edition.projectionRules());
        root.set("delta", edition.delta());
        root.set("occurrences", objectMapper.valueToTree(edition.occurrences()));
        try {
            byte[] bytes = objectMapper.writeValueAsString(canonicalize(root)).getBytes(StandardCharsets.UTF_8);
            return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (JsonProcessingException exception) {
            throw new HandoutValidationException("handout_composition_not_serializable");
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("sha256_unavailable", exception);
        }
    }

    private JsonNode canonicalize(JsonNode node) {
        if (node == null) return objectMapper.nullNode();
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

    private void validateActor(UUID workspaceId, UUID actorUserId) {
        if (workspaceId == null || !workspaces.exists(workspaceId)) throw new WorkspaceNotFoundException();
        if (actorUserId == null || !workspaces.isActiveMember(workspaceId, actorUserId)) {
            throw new ActorNotWorkspaceMemberException();
        }
    }

    private String clean(String value) {
        return value == null ? "" : value.trim();
    }

    private String cleanNullable(String value) {
        String cleaned = clean(value);
        return cleaned.isEmpty() ? null : cleaned;
    }
}
