package com.teachbase.server.editor.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Cross-module read model containing one self-contained frozen editor projection.
 */
public record EditorSnapshotDescriptor(
        UUID editorSnapshotId,
        UUID workspaceId,
        String audience,
        int schemaVersion,
        JsonNode frozenContent,
        String contentHash) {
}
