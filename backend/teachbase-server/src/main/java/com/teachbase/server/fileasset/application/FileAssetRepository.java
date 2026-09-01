package com.teachbase.server.fileasset.application;

import java.util.Optional;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，定义持久化端口，调用方只依赖业务所需的最小能力。
 *
 * 英文术语对照：Persistence port enforcing workspace-local checksum idempotency.
 */
public interface FileAssetRepository {

    Optional<FileRegistration> findByWorkspaceAndSha256(UUID workspaceId, String sha256);

    FileRegistration insert(RegisterFileCommand command);
}
