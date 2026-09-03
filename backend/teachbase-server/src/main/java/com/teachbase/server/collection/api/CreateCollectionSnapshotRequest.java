package com.teachbase.server.collection.api;

import jakarta.validation.constraints.NotNull;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于题篮与快照模块的对外稳定合同层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Freezes the exact draft version and all referenced question packets.
 */
public record CreateCollectionSnapshotRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        long expectedDraftVersion) {
}
