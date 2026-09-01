package com.teachbase.server.editor.application;

import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.NullNode;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，负责业务校验和用例编排，不应泄漏数据库记录或传输层对象。
 * Transaction boundary for the editor aggregate.
 *
 * <p>Every save creates an immutable revision and uses {@code expectedRevisionNo}
 * as an optimistic lock. Snapshots are made only from the current revision, so an
 * export can never accidentally freeze stale browser state.</p>
 */
public class EditorDocumentService {

    private final WorkspaceDirectory workspaces;
    private final EditorContentValidator validator;
    private final EditorDocumentRepository documents;
    private final AuditTrail auditTrail;
    private final ObjectMapper objectMapper;
    private final EditorVariantProjector variantProjector;

    public EditorDocumentService(
            WorkspaceDirectory workspaces,
            EditorContentValidator validator,
            EditorDocumentRepository documents,
            AuditTrail auditTrail,
            ObjectMapper objectMapper,
            EditorVariantProjector variantProjector) {
        this.workspaces = workspaces;
        this.validator = validator;
        this.documents = documents;
        this.auditTrail = auditTrail;
        this.objectMapper = objectMapper;
        this.variantProjector = variantProjector;
    }

    @Transactional
    public EditorDraft create(CreateEditorDocumentCommand command) {
        validateWorkspaceActor(command.workspaceId(), command.actorUserId());
        String kind = command.documentKind() == null ? "" : command.documentKind().trim();
        if (!kind.equals("synchronized_handout") && !kind.equals("independent_question_pack")) {
            throw new EditorContentValidationException("unsupported_editor_document_kind");
        }
        String title = command.title() == null ? "" : command.title().trim();
        if (title.isBlank() || title.length() > 512) {
            throw new EditorContentValidationException("editor_document_title_invalid");
        }
        var content = validator.validate(command.schemaVersion(), command.masterDoc(), command.versionOverrides());
        var draft = documents.create(command, content);
        auditTrail.record(new AuditCommand(
                command.workspaceId(), command.actorUserId(), "editor_document.created", "editor_document",
                draft.editorDocumentId(), Map.of("revisionNo", draft.revisionNo(), "contentHash", draft.contentHash())));
        return draft;
    }

    @Transactional
    public EditorDraft update(UpdateEditorDraftCommand command) {
        validateWorkspaceActor(command.workspaceId(), command.actorUserId());
        if (command.expectedRevisionNo() < 1) {
            throw new EditorContentValidationException("expected_revision_must_be_positive");
        }
        var content = validator.validate(command.schemaVersion(), command.masterDoc(), command.versionOverrides());
        var draft = documents.update(command, content);
        auditTrail.record(new AuditCommand(
                command.workspaceId(), command.actorUserId(), "editor_draft.saved", "editor_document",
                draft.editorDocumentId(), Map.of("revisionNo", draft.revisionNo(), "contentHash", draft.contentHash())));
        return draft;
    }

    @Transactional(readOnly = true)
    public EditorDraft get(UUID editorDocumentId, UUID workspaceId, UUID actorUserId) {
        validateWorkspaceActor(workspaceId, actorUserId);
        return documents.findDraft(editorDocumentId, workspaceId).orElseThrow(EditorDocumentNotFoundException::new);
    }

    @Transactional
    public EditorSnapshot createSnapshot(CreateEditorSnapshotCommand command) {
        validateWorkspaceActor(command.workspaceId(), command.actorUserId());
        String variantKey = command.variantKey() == null ? "" : command.variantKey().trim();
        if (!variantKey.equals("basic") && !variantKey.equals("common") && !variantKey.equals("advanced")) {
            throw new EditorContentValidationException("unsupported_editor_variant");
        }
        String audience = command.audience() == null ? "" : command.audience().trim();
        if (!audience.equals("teacher") && !audience.equals("student")) {
            throw new EditorContentValidationException("unsupported_editor_audience");
        }
        var currentDraft = documents.findDraft(command.editorDocumentId(), command.workspaceId())
                .orElseThrow(EditorDocumentNotFoundException::new);
        if (currentDraft.revisionNo() != command.expectedRevisionNo()) {
            throw new EditorRevisionConflictException(currentDraft.revisionNo());
        }
        // 投影在校验和冻结之前完成，因此落库快照是自包含的，
        // 下游不需要重新解释版本变体规则。
        JsonNode projectedDoc = variantProjector.project(currentDraft, variantKey);
        ArrayNode emptyOverrides = objectMapper.createArrayNode();
        emptyOverrides.add(NullNode.instance).add(NullNode.instance).add(NullNode.instance);
        var projected = validator.validate(command.schemaVersion(), projectedDoc, emptyOverrides);
        var snapshot = documents.createSnapshot(command, projected);
        auditTrail.record(new AuditCommand(
                command.workspaceId(), command.actorUserId(), "editor_snapshot.created", "editor_snapshot",
                snapshot.editorSnapshotId(), Map.of(
                        "documentId", snapshot.editorDocumentId().toString(),
                        "revisionNo", snapshot.revisionNo(),
                        "variantKey", snapshot.variantKey(),
                        "audience", snapshot.audience(),
                        "contentHash", snapshot.contentHash())));
        return snapshot;
    }

    private void validateWorkspaceActor(UUID workspaceId, UUID actorUserId) {
        if (workspaceId == null) throw new EditorContentValidationException("workspace_id_required");
        if (actorUserId == null) throw new EditorContentValidationException("actor_user_id_required");
        if (!workspaces.exists(workspaceId)) throw new WorkspaceNotFoundException();
        if (!workspaces.isActiveMember(workspaceId, actorUserId)) throw new ActorNotWorkspaceMemberException();
    }
}
