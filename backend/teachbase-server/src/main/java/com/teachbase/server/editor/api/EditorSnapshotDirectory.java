package com.teachbase.server.editor.api;

import java.util.Optional;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于在线编辑文档模块的对外稳定合同层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Read port for immutable, export-ready editor snapshots.
 */
public interface EditorSnapshotDirectory {

    Optional<EditorSnapshotDescriptor> find(UUID editorSnapshotId, UUID workspaceId);
}
