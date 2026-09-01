package com.teachbase.server.editor.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Application result for a self-contained, hash-addressed editor snapshot.
 */
public record EditorSnapshot(
        UUID editorSnapshotId,
        UUID editorDocumentId,
        UUID editorRevisionId,
        long revisionNo,
        String variantKey,
        String audience,
        int schemaVersion,
        JsonNode frozenContent,
        String contentHash) {
}
