package com.teachbase.server.editor.api;

/** 中文维护说明：统一导入核心创建 frozen editor revision 的唯一跨模块端口。 */
public interface EditorImportGateway {

    EditorImportResult importFrozenRevision(EditorImportCommand command);
}
