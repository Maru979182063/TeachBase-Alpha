package com.teachbase.server.taxonomy.api;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * 中文维护说明：向标签反馈等调用方提供只读的精确 taxonomy 版本与节点核验，禁止在此接口中隐式解析 latest。
 */
public interface TaxonomySnapshotDirectory {

    Optional<TaxonomySnapshotDescriptor> describe(
            UUID workspaceId, UUID taxonomyVersionId, List<UUID> taxonomyNodeIds);
}
