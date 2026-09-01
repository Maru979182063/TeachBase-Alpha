package com.teachbase.server.source.application;

import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import com.teachbase.server.source.api.RegisterSourceDocumentCommand;
import com.teachbase.server.source.api.RegisterSourceRegionCommand;
import com.teachbase.server.source.api.SourceCatalog;
import com.teachbase.server.source.api.SourceRegistration;
import java.util.Map;
import java.util.Set;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，负责业务校验和用例编排，不应泄漏数据库记录或传输层对象。
 *
 * 英文术语对照：Validates and audits durable source documents and regions.
 */
@Service
public class SourceService implements SourceCatalog {

    private final WorkspaceDirectory workspaces;
    private final SourceRepository sources;
    private final AuditTrail auditTrail;

    public SourceService(WorkspaceDirectory workspaces, SourceRepository sources, AuditTrail auditTrail) {
        this.workspaces = workspaces;
        this.sources = sources;
        this.auditTrail = auditTrail;
    }

    @Override
    @Transactional
    public SourceRegistration registerDocument(RegisterSourceDocumentCommand command) {
        validateActor(command.workspaceId(), command.actorUserId());
        if (command.fileVersionId() == null) throw new SourceValidationException("source_file_version_required");
        if (blank(command.externalSourceKey())) throw new SourceValidationException("source_external_key_required");
        if (!Set.of("docx", "pdf", "image", "structured_import", "other").contains(command.sourceType())) {
            throw new SourceValidationException("source_type_invalid");
        }
        if (command.metadata() == null || !command.metadata().isObject()) {
            throw new SourceValidationException("source_metadata_invalid");
        }
        var result = sources.registerDocument(command);
        if (result.created()) {
            auditTrail.record(new AuditCommand(
                    command.workspaceId(), command.actorUserId(), "source_document.registered",
                    "source_document", result.id(), Map.of("externalSourceKey", command.externalSourceKey())));
        }
        return result;
    }

    @Override
    @Transactional
    public SourceRegistration registerRegion(RegisterSourceRegionCommand command) {
        validateActor(command.workspaceId(), command.actorUserId());
        if (command.sourceDocumentId() == null) throw new SourceValidationException("source_document_required");
        if (blank(command.externalRegionKey())) throw new SourceValidationException("source_region_key_required");
        if (!Set.of("page", "block", "question", "image", "formula", "table", "other")
                .contains(command.regionType())) {
            throw new SourceValidationException("source_region_type_invalid");
        }
        if (command.sourceReference() == null || !command.sourceReference().isObject()) {
            throw new SourceValidationException("source_reference_invalid");
        }
        var result = sources.registerRegion(command);
        if (result.created()) {
            auditTrail.record(new AuditCommand(
                    command.workspaceId(), command.actorUserId(), "source_region.registered",
                    "source_region", result.id(), Map.of("externalRegionKey", command.externalRegionKey())));
        }
        return result;
    }

    private void validateActor(java.util.UUID workspaceId, java.util.UUID actorUserId) {
        if (!workspaces.exists(workspaceId)) throw new WorkspaceNotFoundException();
        if (!workspaces.isActiveMember(workspaceId, actorUserId)) throw new ActorNotWorkspaceMemberException();
    }

    private boolean blank(String value) {
        return value == null || value.isBlank();
    }
}
