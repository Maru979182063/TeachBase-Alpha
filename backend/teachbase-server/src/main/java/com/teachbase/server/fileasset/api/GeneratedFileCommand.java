package com.teachbase.server.fileasset.api;

import java.util.UUID;

/**
 * 中文维护说明：本文件属于文件资产模块的对外稳定合同层，封装跨层调用参数，不能用它绕过对应应用服务的校验。
 *
 * 英文术语对照：Internal registration command for finalized bytes produced by a backend worker.
 */
public record GeneratedFileCommand(
        UUID workspaceId,
        UUID actorUserId,
        String originalFilename,
        String storageKey,
        String mediaType,
        long sizeBytes,
        String sha256) {
}
