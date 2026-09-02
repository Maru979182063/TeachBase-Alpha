package com.teachbase.server.editor.application;

/**
 * 中文维护说明：文档写入模式与当前 writer 不匹配时 fail closed，防止旧 pointer 和 working draft 同时成为真相源。
 *
 * 英文术语对照：Writer mode prevents this process from mutating the document.
 */
public class EditorWriterFencedException extends RuntimeException {

    public EditorWriterFencedException() {
        super("editor_writer_fenced");
    }
}
