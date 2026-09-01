package com.teachbase.server.exporting.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.exporting.application.ExportRequestDetails;
import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于稳定导出与渲染队列模块的对外稳定合同层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Queue, attempt, failure, and generated-file status visible to API clients.
 */
public record ExportRequestDetailsResponse(
        UUID exportRequestId,
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
        ExportedFileResponse file) {

    static ExportRequestDetailsResponse from(ExportRequestDetails details) {
        ExportedFileResponse file = details.fileVersionId() == null ? null : new ExportedFileResponse(
                details.fileVersionId(), details.storageKey(), details.mediaType(), details.sizeBytes(), details.sha256());
        return new ExportRequestDetailsResponse(
                details.exportRequestId(), details.editorSnapshotId(), details.format(), details.status(),
                details.attemptCount(), details.maxAttempts(), details.rendererProfile(), details.rendererVersion(),
                details.error(), details.requestedAt(), details.completedAt(), file);
    }

    public record ExportedFileResponse(
            UUID fileVersionId,
            String storageKey,
            String mediaType,
            Long sizeBytes,
            String sha256) {
    }
}
