package com.teachbase.server.collection.api;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Replaces the ordered draft atomically and records an autosave or manual checkpoint.
 */
public record SaveCollectionDraftRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        long expectedDraftVersion,
        @NotNull String checkpointKind,
        @NotNull @Size(max = 1000) List<@Valid CollectionItemRequest> items) {
}
