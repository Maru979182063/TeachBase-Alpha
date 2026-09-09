package com.teachbase.server.editor.api;

import java.util.Optional;
import java.util.UUID;

/** 中文维护说明：按 workspace 和精确 revision 查询，不允许读取 latest 替代固定版本。 */
public interface EditorRevisionDirectory {
    Optional<EditorRevisionDescriptor> find(UUID workspaceId, UUID editorDocumentId, UUID editorRevisionId);
}
