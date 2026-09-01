package com.teachbase.server.question.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import com.teachbase.server.question.api.BulkQuestionImportRequest;
import com.teachbase.server.question.api.BulkQuestionImportResponse;
import com.teachbase.server.question.api.QuestionBatchImporter;
import com.teachbase.server.question.api.QuestionHashPreview;
import com.teachbase.server.question.api.QuestionHashPreviewer;
import com.teachbase.server.question.api.QuestionImportItem;
import com.teachbase.server.question.api.QuestionSearchResponse;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;
import java.time.OffsetDateTime;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，负责业务校验和用例编排，不应泄漏数据库记录或传输层对象。
 * Validates pipeline packets and establishes the stable identity/immutable revision
 * boundary. Content is canonicalized before hashing so harmless JSON key ordering
 * differences do not create duplicate revisions during replayed ingestion.
 */
@Service
public class QuestionService implements QuestionBatchImporter, QuestionHashPreviewer {

    private static final int MAX_MARKDOWN_LENGTH = 2_000_000;
    private final WorkspaceDirectory workspaces;
    private final QuestionRepository questions;
    private final AuditTrail auditTrail;
    private final ObjectMapper objectMapper;

    public QuestionService(
            WorkspaceDirectory workspaces,
            QuestionRepository questions,
            AuditTrail auditTrail,
            ObjectMapper objectMapper) {
        this.workspaces = workspaces;
        this.questions = questions;
        this.auditTrail = auditTrail;
        this.objectMapper = objectMapper;
    }

    @Transactional
    @Override
    public BulkQuestionImportResponse importBatch(BulkQuestionImportRequest request) {
        validateWorkspaceActor(request.workspaceId(), request.actorUserId());
        var outcomes = new ArrayList<com.teachbase.server.question.api.QuestionImportResult>();
        for (QuestionImportItem item : request.questions()) {
            var result = questions.importRevision(normalize(request.workspaceId(), request.actorUserId(), item));
            outcomes.add(result);
            if (result.createdRevision()) {
                auditTrail.record(new AuditCommand(
                        request.workspaceId(), request.actorUserId(), "question_revision.imported", "question",
                        result.questionId(), Map.of(
                                "questionRevisionId", result.questionRevisionId().toString(),
                                "revisionNo", result.revisionNo(),
                                "reviewStatus", result.reviewStatus())));
            }
        }
        return new BulkQuestionImportResponse(List.copyOf(outcomes));
    }

    @Transactional(readOnly = true)
    public QuestionSearchResponse search(
            UUID workspaceId,
            UUID actorUserId,
            String requestedReviewStatus,
            String query,
            String subject,
            String stage,
            String grade,
            String questionType,
            Integer difficultyStars,
            String cursor,
            int requestedLimit) {
        validateWorkspaceActor(workspaceId, actorUserId);
        int limit = requestedLimit == 0 ? 30 : requestedLimit;
        if (limit < 1 || limit > 100) throw new QuestionValidationException("question_search_limit_invalid");
        if (difficultyStars != null && (difficultyStars < 1 || difficultyStars > 5)) {
            throw new QuestionValidationException("question_difficulty_invalid");
        }
        String reviewStatus = clean(requestedReviewStatus);
        if (!java.util.Set.of("approved", "unreviewed", "pending_review", "rejected").contains(reviewStatus)) {
            throw new QuestionValidationException("question_review_status_invalid");
        }
        var items = questions.search(
                workspaceId, reviewStatus, clean(query), clean(subject), clean(stage), clean(grade),
                clean(questionType), difficultyStars, decodeCursor(cursor), limit + 1);
        String nextCursor = null;
        if (items.size() > limit) {
            var boundary = items.get(limit - 1);
            nextCursor = encodeCursor(boundary.revisionCreatedAt(), boundary.questionId());
            items = new ArrayList<>(items.subList(0, limit));
        }
        return new QuestionSearchResponse(List.copyOf(items), limit, nextCursor);
    }

    @Override
    public QuestionHashPreview previewHashes(QuestionImportItem item) {
        var normalized = normalize(new UUID(0L, 0L), new UUID(0L, 0L), item);
        return new QuestionHashPreview(
                normalized.contentHash(), normalized.sourcePayloadHash(), normalized.importEnvelopeHash());
    }

    private NormalizedQuestionRevision normalize(UUID workspaceId, UUID actorUserId, QuestionImportItem item) {
        String reviewStatus = clean(item.reviewStatus());
        // 终态审核结论归审核模块所有。导入流程只能把内容送入待审核，
        // 不能自行发布或驳回自己的产物。
        if (!java.util.Set.of("unreviewed", "pending_review").contains(reviewStatus)) {
            throw new QuestionValidationException("question_review_status_invalid");
        }
        Integer difficulty = item.difficultyStars();
        if (difficulty != null && (difficulty < 1 || difficulty > 5)) {
            throw new QuestionValidationException("question_difficulty_invalid");
        }
        validateArray(item.secondaryKnowledgeTags(), "question_secondary_tags_invalid");
        validateArray(item.options(), "question_options_invalid");
        if (!item.content().isObject()) throw new QuestionValidationException("question_content_invalid");
        if (!item.provenance().isObject()) throw new QuestionValidationException("question_provenance_invalid");

        String material = markdown(item.materialMarkdown());
        String stem = markdown(item.stemMarkdown());
        String answer = markdown(item.answerMarkdown());
        String analysis = markdown(item.analysisMarkdown());
        if (stem.isBlank()) throw new QuestionValidationException("question_stem_required");

        JsonNode tags = canonicalize(item.secondaryKnowledgeTags());
        JsonNode options = canonicalize(item.options());
        JsonNode content = canonicalize(item.content());
        JsonNode provenance = canonicalize(item.provenance());
        ObjectNode semanticContent = objectMapper.createObjectNode();
        semanticContent.put("subject", clean(item.subject()));
        semanticContent.put("stage", clean(item.stage()));
        semanticContent.put("grade", clean(item.grade()));
        semanticContent.put("questionType", clean(item.questionType()));
        semanticContent.put("title", clean(item.title()));
        semanticContent.put("lesson", clean(item.lesson()));
        semanticContent.put("primaryKnowledgeTag", clean(item.primaryKnowledgeTag()));
        semanticContent.set("secondaryKnowledgeTags", tags);
        if (difficulty == null) semanticContent.putNull("difficultyStars");
        else semanticContent.put("difficultyStars", difficulty);
        semanticContent.put("materialMarkdown", material);
        semanticContent.put("stemMarkdown", stem);
        semanticContent.set("options", options);
        semanticContent.put("answerMarkdown", answer);
        semanticContent.put("analysisMarkdown", analysis);
        semanticContent.set("content", content);
        String contentHash = sha256(canonicalize(semanticContent));
        String declaredContentHash = clean(item.contentHash()).toLowerCase(java.util.Locale.ROOT);
        if (!declaredContentHash.isBlank()
                && (!declaredContentHash.matches("[0-9a-f]{64}") || !declaredContentHash.equals(contentHash))) {
            throw new QuestionValidationException("question_content_hash_mismatch");
        }

        ObjectNode sourcePayload = objectMapper.createObjectNode();
        sourcePayload.put("sourceSystem", clean(item.sourceSystem()));
        sourcePayload.put("sourceKey", clean(item.sourceKey()));
        sourcePayload.set("semanticContent", semanticContent);
        sourcePayload.set("provenance", provenance);
        String sourcePayloadHash = suppliedOrComputedHash(item.sourcePayloadHash(), sourcePayload,
                "question_source_payload_hash_invalid");

        ObjectNode importEnvelope = objectMapper.createObjectNode();
        importEnvelope.put("externalKey", clean(item.externalKey()));
        importEnvelope.put("reviewStatus", reviewStatus);
        importEnvelope.put("contentHash", contentHash);
        importEnvelope.put("sourcePayloadHash", sourcePayloadHash);
        importEnvelope.set("provenance", provenance);
        String importEnvelopeHash = suppliedOrComputedHash(item.importEnvelopeHash(), importEnvelope,
                "question_import_envelope_hash_invalid");

        return new NormalizedQuestionRevision(
                workspaceId, actorUserId, clean(item.externalKey()), clean(item.sourceSystem()), clean(item.sourceKey()),
                reviewStatus, clean(item.subject()), clean(item.stage()), clean(item.grade()), clean(item.questionType()),
                clean(item.title()), clean(item.lesson()), clean(item.primaryKnowledgeTag()), tags, difficulty, material,
                stem, options, answer, analysis, content, provenance, contentHash,
                sourcePayloadHash, importEnvelopeHash);
    }

    private String suppliedOrComputedHash(String supplied, JsonNode fallbackPayload, String errorCode) {
        String value = clean(supplied).toLowerCase(java.util.Locale.ROOT);
        if (value.isBlank()) return sha256(canonicalize(fallbackPayload));
        if (!value.matches("[0-9a-f]{64}")) throw new QuestionValidationException(errorCode);
        return value;
    }

    private void validateArray(JsonNode value, String code) {
        if (value == null || !value.isArray()) throw new QuestionValidationException(code);
    }

    private String markdown(String value) {
        String result = value == null ? "" : value.strip();
        if (result.length() > MAX_MARKDOWN_LENGTH || result.indexOf('\0') >= 0) {
            throw new QuestionValidationException("question_markdown_invalid");
        }
        return result;
    }

    private String clean(String value) {
        return value == null ? "" : value.trim();
    }

    private QuestionSearchCursor decodeCursor(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            String decoded = new String(Base64.getUrlDecoder().decode(value), java.nio.charset.StandardCharsets.UTF_8);
            String[] parts = decoded.split("\\|", 2);
            return new QuestionSearchCursor(OffsetDateTime.parse(parts[0]), UUID.fromString(parts[1]));
        } catch (RuntimeException exception) {
            throw new QuestionValidationException("question_search_cursor_invalid");
        }
    }

    private String encodeCursor(OffsetDateTime createdAt, UUID questionId) {
        String value = createdAt + "|" + questionId;
        return Base64.getUrlEncoder().withoutPadding()
                .encodeToString(value.getBytes(java.nio.charset.StandardCharsets.UTF_8));
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

    private String sha256(JsonNode value) {
        try {
            byte[] canonical = objectMapper.writeValueAsBytes(value);
            return java.util.HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(canonical));
        } catch (JsonProcessingException exception) {
            throw new QuestionValidationException("question_content_not_serializable");
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("sha256_unavailable", exception);
        }
    }

    private void validateWorkspaceActor(UUID workspaceId, UUID actorUserId) {
        if (workspaceId == null) throw new QuestionValidationException("workspace_id_required");
        if (actorUserId == null) throw new QuestionValidationException("actor_user_id_required");
        if (!workspaces.exists(workspaceId)) throw new WorkspaceNotFoundException();
        if (!workspaces.isActiveMember(workspaceId, actorUserId)) throw new ActorNotWorkspaceMemberException();
    }
}
