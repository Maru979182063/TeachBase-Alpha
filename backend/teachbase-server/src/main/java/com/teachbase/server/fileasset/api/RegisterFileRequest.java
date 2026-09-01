package com.teachbase.server.fileasset.api;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Client-supplied metadata for bytes already written through an approved storage adapter.
 */
public record RegisterFileRequest(
        @NotNull UUID workspaceId,
        UUID actorUserId,
        @NotBlank @Size(max = 512) String originalFilename,
        @NotBlank String storageProvider,
        @NotBlank @Size(max = 1024) String storageKey,
        @NotBlank @Size(max = 255) String mediaType,
        @PositiveOrZero long sizeBytes,
        @NotBlank String sha256) {
}
