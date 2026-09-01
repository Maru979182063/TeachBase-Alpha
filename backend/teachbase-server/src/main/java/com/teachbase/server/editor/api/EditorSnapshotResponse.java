package com.teachbase.server.editor.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.editor.application.EditorSnapshot;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Created immutable editor snapshot returned to an API client.
 */
public record EditorSnapshotResponse(
        UUID editorSnapshotId,
        UUID editorDocumentId,
        UUID editorRevisionId,
        long revisionNo,
        String variantKey,
        String audience,
        int schemaVersion,
        JsonNode frozenContent,
        String contentHash) {

    static EditorSnapshotResponse from(EditorSnapshot snapshot) {
        return new EditorSnapshotResponse(
                snapshot.editorSnapshotId(), snapshot.editorDocumentId(), snapshot.editorRevisionId(),
                snapshot.revisionNo(), snapshot.variantKey(), snapshot.audience(), snapshot.schemaVersion(),
                snapshot.frozenContent(), snapshot.contentHash());
    }
}
