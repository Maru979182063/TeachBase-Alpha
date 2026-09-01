package com.teachbase.server.exporting.infrastructure;

import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import com.teachbase.server.exporting.application.ExportExecutionRepository;
import com.teachbase.server.exporting.application.ExportWorkItem;
import com.teachbase.server.fileasset.api.GeneratedFileCommand;
import com.teachbase.server.fileasset.api.GeneratedFileRegistrar;
import java.time.Duration;
import java.util.Map;
import java.util.Optional;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

@Component
/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，负责业务校验和用例编排，不应泄漏数据库记录或传输层对象。
 * Keeps queue state transitions, generated-file registration, and audit records in
 * explicit transactions. Heartbeat/failure use independent transactions so they can
 * commit even when rendering work outside the database fails.
 */
class ExportExecutionCoordinator {

    private final ExportExecutionRepository exports;
    private final GeneratedFileRegistrar files;
    private final AuditTrail auditTrail;

    ExportExecutionCoordinator(
            ExportExecutionRepository exports,
            GeneratedFileRegistrar files,
            AuditTrail auditTrail) {
        this.exports = exports;
        this.files = files;
        this.auditTrail = auditTrail;
    }

    @Transactional
    public Optional<ExportWorkItem> claimNext(String workerId, Duration leaseDuration) {
        return exports.claimNext(workerId, leaseDuration);
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public boolean heartbeat(ExportWorkItem item, Duration leaseDuration) {
        return exports.heartbeat(item, leaseDuration);
    }

    @Transactional
    public RegisteredArtifact complete(ExportWorkItem item, RenderedArtifact artifact) {
        var registration = files.registerGeneratedFile(new GeneratedFileCommand(
                item.workspaceId(),
                item.requestedBy(),
                artifact.originalFilename(),
                artifact.storageKey(),
                artifact.mediaType(),
                artifact.sizeBytes(),
                artifact.sha256()));
        exports.complete(
                item,
                registration.fileVersionId(),
                artifact.rendererVersion(),
                artifact.renderSourceEnvelope(),
                artifact.renderSourceHash(),
                registration.storageKey(),
                artifact.sha256());
        auditTrail.record(new AuditCommand(
                item.workspaceId(),
                item.requestedBy(),
                "export_request.completed",
                "export_request",
                item.exportRequestId(),
                Map.of(
                        "format", item.format(),
                        "attemptNo", item.attemptNo(),
                        "fileVersionId", registration.fileVersionId().toString(),
                        "storageKey", registration.storageKey(),
                        "sha256", artifact.sha256())));
        return new RegisteredArtifact(registration.fileVersionId(), registration.storageKey(), registration.created());
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public String fail(ExportWorkItem item, String errorCode, boolean retryable) {
        String status = exports.fail(item, errorCode, retryable);
        auditTrail.record(new AuditCommand(
                item.workspaceId(),
                item.requestedBy(),
                "export_request." + status,
                "export_request",
                item.exportRequestId(),
                Map.of("errorCode", errorCode, "attemptNo", item.attemptNo(), "retryable", status.equals("failed_retryable"))));
        return status;
    }

    record RegisteredArtifact(java.util.UUID fileVersionId, String storageKey, boolean created) {
    }
}
