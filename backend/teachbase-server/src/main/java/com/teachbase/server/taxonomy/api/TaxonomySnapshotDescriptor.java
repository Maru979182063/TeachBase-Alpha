package com.teachbase.server.taxonomy.api;

import java.util.List;
import java.util.UUID;

/**
 * 中文维护说明：这是精确知识树版本的只读描述，节点列表仅包含调用方明确请求并验证存在的节点。
 */
public record TaxonomySnapshotDescriptor(
        UUID taxonomyVersionId,
        String taxonomyKey,
        String subject,
        String stage,
        String status,
        List<UUID> taxonomyNodeIds) {
}
