package com.teachbase.server.exporting.infrastructure;

import com.fasterxml.jackson.databind.JsonNode;
import java.nio.file.Path;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Validated local artifact and reproducible source metadata awaiting registration.
 */
record RenderedArtifact(
        Path path,
        String storageKey,
        String originalFilename,
        String mediaType,
        long sizeBytes,
        String sha256,
        String rendererVersion,
        JsonNode renderSourceEnvelope,
        String renderSourceHash) {
}
