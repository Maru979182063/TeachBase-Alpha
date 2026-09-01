package com.teachbase.server.exporting.api;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Idempotent request to render one immutable editor snapshot into a supported format.
 */
public record CreateExportRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotNull UUID editorSnapshotId,
        @NotBlank String format,
        @NotBlank @Size(max = 128) String idempotencyKey,
        UUID retryOfExportRequestId) {
}
