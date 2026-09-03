package com.teachbase.server.fileasset.application;

import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import com.teachbase.server.fileasset.domain.DomainValidationException;
import com.teachbase.server.fileasset.domain.OriginalFilename;
import com.teachbase.server.fileasset.domain.Sha256;
import com.teachbase.server.fileasset.domain.StorageKey;
import com.teachbase.server.fileasset.api.GeneratedFileCommand;
import com.teachbase.server.fileasset.api.GeneratedFileRegistrar;
import com.teachbase.server.fileasset.api.GeneratedFileRegistration;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
/**
 * 中文维护说明：本文件属于文件资产模块的业务规则与事务编排层，负责业务校验和用例编排，不应泄漏数据库记录或传输层对象。
 * Validates portable file metadata and de-duplicates immutable bytes by workspace
 * and SHA-256. The operation is safe to retry after an uncertain client response.
 */
public class FileRegistrationService implements GeneratedFileRegistrar {

    private final WorkspaceDirectory workspaces;
    private final FileAssetRepository files;
    private final AuditTrail auditTrail;

    public FileRegistrationService(
            WorkspaceDirectory workspaces,
            FileAssetRepository files,
            AuditTrail auditTrail) {
        this.workspaces = workspaces;
        this.files = files;
        this.auditTrail = auditTrail;
    }

    @Transactional
    public FileRegistration register(RegisterFileCommand rawCommand) {
        if (rawCommand.workspaceId() == null) {
            throw new DomainValidationException("workspace_id_required");
        }
        if (!workspaces.exists(rawCommand.workspaceId())) {
            throw new WorkspaceNotFoundException();
        }
        if (rawCommand.actorUserId() != null
                && !workspaces.isActiveMember(rawCommand.workspaceId(), rawCommand.actorUserId())) {
            throw new ActorNotWorkspaceMemberException();
        }
        if (rawCommand.sizeBytes() < 0) {
            throw new DomainValidationException("size_bytes_must_not_be_negative");
        }
        String mediaType = rawCommand.mediaType() == null ? "" : rawCommand.mediaType().trim();
        if (mediaType.isBlank()) {
            throw new DomainValidationException("media_type_required");
        }
        String provider = rawCommand.storageProvider() == null ? "" : rawCommand.storageProvider().trim();
        if (!provider.equals("local") && !provider.equals("object_storage")) {
            throw new DomainValidationException("unsupported_storage_provider");
        }

        var filename = new OriginalFilename(rawCommand.originalFilename());
        var storageKey = new StorageKey(rawCommand.storageKey());
        var sha256 = new Sha256(rawCommand.sha256());
        var command = new RegisterFileCommand(
                rawCommand.workspaceId(),
                rawCommand.actorUserId(),
                filename.value(),
                provider,
                storageKey.value(),
                mediaType,
                rawCommand.sizeBytes(),
                sha256.value());

        // 这里提供快速幂等路径；多个调用方用同一校验和并发竞争时，
        // 最终仍以仓储层的唯一约束作为一致性裁决。
        var existing = files.findByWorkspaceAndSha256(command.workspaceId(), command.sha256());
        if (existing.isPresent()) {
            return existing.get();
        }

        var result = files.insert(command);
        if (result.created()) {
            auditTrail.record(new AuditCommand(
                    command.workspaceId(),
                    command.actorUserId(),
                    "file_asset.registered",
                    "file_asset",
                    result.fileAssetId(),
                    Map.of(
                            "fileVersionId", result.fileVersionId().toString(),
                            "storageProvider", result.storageProvider(),
                            "storageKey", result.storageKey(),
                            "sha256", result.sha256(),
                            "sizeBytes", result.sizeBytes())));
        }
        return result;
    }

    @Override
    public GeneratedFileRegistration registerGeneratedFile(GeneratedFileCommand command) {
        var result = register(new RegisterFileCommand(
                command.workspaceId(),
                command.actorUserId(),
                command.originalFilename(),
                "local",
                command.storageKey(),
                command.mediaType(),
                command.sizeBytes(),
                command.sha256()));
        return new GeneratedFileRegistration(result.fileVersionId(), result.storageKey(), result.created());
    }
}
