package com.teachbase.server.editor.application;

import com.teachbase.server.editor.api.EditorImportCommand;
import com.teachbase.server.editor.api.EditorImportResult;

/** 中文维护说明：持久化稳定导入身份和不可变 editor revision，不创建 preview 或 snapshot。 */
public interface EditorImportRepository {

    EditorImportResult importFrozen(EditorImportCommand command, ValidatedEditorContent content);
}
