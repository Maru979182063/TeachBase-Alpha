package com.teachbase.server.exporting.application;

import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import com.teachbase.server.editor.api.EditorSnapshotDirectory;
import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
/**
 * 中文维护说明：本文件属于稳定导出与渲染队列模块的业务规则与事务编排层，负责业务校验和用例编排，不应泄漏数据库记录或传输层对象。
 *
 * 英文术语对照：Validates snapshot-bound export requests and applies workspace idempotency.
 */
public class ExportRequestService {

    private final WorkspaceDirectory workspaces;
    private final EditorSnapshotDirectory snapshots;
    private final ExportRequestRepository exports;
    private final AuditTrail auditTrail;

    public ExportRequestService(
            WorkspaceDirectory workspaces,
            EditorSnapshotDirectory snapshots,
            ExportRequestRepository exports,
            AuditTrail auditTrail) {
        this.workspaces = workspaces;
        this.snapshots = snapshots;
        this.exports = exports;
        this.auditTrail = auditTrail;
    }

    @Transactional
    public ExportRequestState create(CreateExportCommand raw) {
        if (raw.workspaceId() == null) throw new ExportValidationException("workspace_id_required");
        if (raw.actorUserId() == null) throw new ExportValidationException("actor_user_id_required");
        if (!workspaces.exists(raw.workspaceId())) throw new WorkspaceNotFoundException();
        if (!workspaces.isActiveMember(raw.workspaceId(), raw.actorUserId())) {
            throw new ActorNotWorkspaceMemberException();
        }
        if (raw.editorSnapshotId() == null || snapshots.find(raw.editorSnapshotId(), raw.workspaceId()).isEmpty()) {
            throw new EditorSnapshotNotFoundException();
        }
        String format = raw.format() == null ? "" : raw.format().trim().toLowerCase();
        if (!format.equals("docx") && !format.equals("pdf")) {
            throw new ExportValidationException("unsupported_export_format");
        }
        String key = raw.idempotencyKey() == null ? "" : raw.idempotencyKey().trim();
        if (key.isBlank() || key.length() > 128) {
            throw new ExportValidationException("export_idempotency_key_invalid");
        }
        if (raw.retryOfExportRequestId() != null && !exports.exists(raw.workspaceId(), raw.retryOfExportRequestId())) {
            throw new ExportValidationException("retry_export_request_not_found");
        }
        var command = new CreateExportCommand(
                raw.workspaceId(), raw.actorUserId(), raw.editorSnapshotId(), format, key, raw.retryOfExportRequestId());
        var result = exports.create(command);
        if (result.created()) {
            auditTrail.record(new AuditCommand(
                    command.workspaceId(), command.actorUserId(), "export_request.created", "export_request",
                    result.exportRequestId(), Map.of(
                            "snapshotId", result.editorSnapshotId().toString(),
                            "format", result.format(),
                            "status", result.status())));
        }
        return result;
    }

    @Transactional(readOnly = true)
    public ExportRequestDetails get(UUID exportRequestId, UUID workspaceId, UUID actorUserId) {
        if (exportRequestId == null) throw new ExportValidationException("export_request_id_required");
        if (workspaceId == null) throw new ExportValidationException("workspace_id_required");
        if (actorUserId == null) throw new ExportValidationException("actor_user_id_required");
        if (!workspaces.exists(workspaceId)) throw new WorkspaceNotFoundException();
        if (!workspaces.isActiveMember(workspaceId, actorUserId)) throw new ActorNotWorkspaceMemberException();
        return exports.findById(workspaceId, exportRequestId).orElseThrow(ExportRequestNotFoundException::new);
    }
}
