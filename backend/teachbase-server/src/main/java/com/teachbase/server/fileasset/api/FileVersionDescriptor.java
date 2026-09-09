package com.teachbase.server.fileasset.api;

import java.util.UUID;

/** 中文维护说明：导入预检读取的精确文件版本描述，不暴露存储实现细节。 */
public record FileVersionDescriptor(
        UUID fileVersionId,
        UUID workspaceId,
        String storageKey,
        String mediaType,
        long sizeBytes,
        String sha256) {
}
