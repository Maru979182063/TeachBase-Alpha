package com.teachbase.server.fileasset.application;

import java.util.UUID;

/**
 * 中文维护说明：本文件属于文件资产模块的业务规则与事务编排层，封装跨层调用参数，不能用它绕过对应应用服务的校验。
 *
 * 英文术语对照：Normalized application command after filename, key, and checksum validation.
 */
public record RegisterFileCommand(
        UUID workspaceId,
        UUID actorUserId,
        String originalFilename,
        String storageProvider,
        String storageKey,
        String mediaType,
        long sizeBytes,
        String sha256) {
}
