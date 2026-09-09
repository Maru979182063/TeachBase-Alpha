package com.teachbase.server.editor.api;

import java.util.UUID;

/** 中文维护说明：跨模块只读的精确 editor revision 描述，不暴露 working draft。 */
public record EditorRevisionDescriptor(
        UUID editorDocumentId,
        UUID editorRevisionId,
        UUID workspaceId,
        long revisionNo,
        String contentHash) {
}
