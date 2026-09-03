package com.teachbase.server.collection.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于题篮与快照模块的对外稳定合同层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Recoverable checkpoint metadata and self-contained draft content.
 */
public record CollectionCheckpointResponse(
        UUID questionCollectionCheckpointId,
        long draftVersion,
        String checkpointKind,
        String contentHash,
        JsonNode content,
        OffsetDateTime createdAt,
        OffsetDateTime expiresAt) {
}
