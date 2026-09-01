package com.teachbase.server.exporting.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Complete application read model for export status and output metadata.
 */
public record ExportRequestDetails(
        UUID exportRequestId,
        UUID workspaceId,
        UUID editorSnapshotId,
        String format,
        String status,
        int attemptCount,
        int maxAttempts,
        String rendererProfile,
        String rendererVersion,
        JsonNode error,
        OffsetDateTime requestedAt,
        OffsetDateTime completedAt,
        UUID fileVersionId,
        String storageKey,
        String mediaType,
        Long sizeBytes,
        String sha256) {
}
