package com.teachbase.server.editor.api;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Confirms and freezes one current revision, variant, and audience projection.
 */
public record CreateEditorSnapshotRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @Positive long expectedRevisionNo,
        @NotBlank String variantKey,
        @NotBlank String audience,
        int schemaVersion) {
}
