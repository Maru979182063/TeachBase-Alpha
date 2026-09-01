package com.teachbase.server.collection.api;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Creates an empty question basket at draft version zero.
 */
public record CreateCollectionRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotBlank @Size(max = 512) String name) {
}
