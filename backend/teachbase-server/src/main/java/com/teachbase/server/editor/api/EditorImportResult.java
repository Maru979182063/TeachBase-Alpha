package com.teachbase.server.editor.api;

import java.util.UUID;

/** 中文维护说明：Canonical Import 创建或复用 editor 稳定身份与精确 revision 的结果。 */
public record EditorImportResult(
        UUID editorDocumentId,
        UUID editorRevisionId,
        long revisionNo,
        String contentHash,
        boolean createdDocument,
        boolean createdRevision) {
}
