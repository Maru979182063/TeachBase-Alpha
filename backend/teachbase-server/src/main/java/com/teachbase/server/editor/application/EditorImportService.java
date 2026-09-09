package com.teachbase.server.editor.application;

import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import com.teachbase.server.editor.api.EditorImportCommand;
import com.teachbase.server.editor.api.EditorImportGateway;
import com.teachbase.server.editor.api.EditorImportResult;
import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 中文维护说明：受控导入只冻结 revision；普通浏览器 autosave 仍由 WP-01 service 负责，
 * 两者不能共享随机 UUID 或绕过 workspace 校验。
 */
@Service
public class EditorImportService implements EditorImportGateway {

    private final WorkspaceDirectory workspaces;
    private final EditorContentValidator validator;
    private final EditorImportRepository repository;
    private final AuditTrail auditTrail;

    public EditorImportService(
            WorkspaceDirectory workspaces,
            EditorContentValidator validator,
            EditorImportRepository repository,
            AuditTrail auditTrail) {
        this.workspaces = workspaces;
        this.validator = validator;
        this.repository = repository;
        this.auditTrail = auditTrail;
    }

    @Override
    @Transactional
    public EditorImportResult importFrozenRevision(EditorImportCommand command) {
        validateActor(command);
        String key = clean(command.importDocumentKey());
        String kind = clean(command.documentKind());
        String title = clean(command.title());
        if (key.isEmpty() || key.length() > 240) {
            throw new EditorContentValidationException("editor_import_identity_key_invalid");
        }
        if (!java.util.Set.of("synchronized_handout", "independent_question_pack").contains(kind)) {
            throw new EditorContentValidationException("unsupported_editor_document_kind");
        }
        if (title.isEmpty() || title.length() > 512) {
            throw new EditorContentValidationException("editor_document_title_invalid");
        }
        var normalized = new EditorImportCommand(
                command.workspaceId(), command.actorUserId(), key, kind, title,
                command.schemaVersion(), command.masterDoc(), command.versionOverrides());
        ValidatedEditorContent content = validator.validate(
                command.schemaVersion(), command.masterDoc(), command.versionOverrides());
        EditorImportResult result = repository.importFrozen(normalized, content);
        if (result.createdRevision()) {
            auditTrail.record(new AuditCommand(
                    command.workspaceId(), command.actorUserId(), "editor_revision.canonical_imported",
                    "editor_document", result.editorDocumentId(), Map.of(
                            "editorRevisionId", result.editorRevisionId().toString(),
                            "revisionNo", result.revisionNo(), "contentHash", result.contentHash())));
        }
        return result;
    }

    private void validateActor(EditorImportCommand command) {
        if (command.workspaceId() == null || !workspaces.exists(command.workspaceId())) {
            throw new WorkspaceNotFoundException();
        }
        if (command.actorUserId() == null
                || !workspaces.isActiveMember(command.workspaceId(), command.actorUserId())) {
            throw new ActorNotWorkspaceMemberException();
        }
    }

    private String clean(String value) {
        return value == null ? "" : value.trim();
    }
}
