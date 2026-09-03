package com.teachbase.server.collection.application;

import com.teachbase.server.collection.api.CollectionItemResponse;
import java.util.List;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于题篮与快照模块的业务规则与事务编排层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Application representation of the current ordered collection draft.
 */
public record CollectionDraft(
        UUID questionCollectionId,
        UUID workspaceId,
        String name,
        String status,
        long draftVersion,
        List<CollectionItemResponse> items) {
}
