package com.teachbase.server.editor.application;

/**
 * 中文维护说明：本文件属于在线编辑文档模块的业务规则与事务编排层，表达可识别的业务失败，错误码和重试语义属于对外合同。
 *
 * 英文术语对照：Workspace-scoped editor aggregate was not found or is no longer active.
 */
public class EditorDocumentNotFoundException extends RuntimeException {

    public EditorDocumentNotFoundException() {
        super("editor_document_not_found");
    }
}
