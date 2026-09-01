package com.teachbase.server.fileasset.application;

import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Application result describing the winning or previously existing file version.
 */
public record FileRegistration(
        UUID fileAssetId,
        UUID fileVersionId,
        UUID workspaceId,
        String originalFilename,
        String storageProvider,
        String storageKey,
        String mediaType,
        long sizeBytes,
        String sha256,
        boolean created) {
}
