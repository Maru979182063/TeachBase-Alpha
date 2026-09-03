package com.teachbase.server.collection.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于题篮与快照模块的业务规则与事务编排层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Frozen collection result returned from persistence.
 */
public record CollectionSnapshot(
        UUID snapshotId,
        UUID collectionId,
        long sourceDraftVersion,
        String contentHash,
        JsonNode frozenContent) {
}
