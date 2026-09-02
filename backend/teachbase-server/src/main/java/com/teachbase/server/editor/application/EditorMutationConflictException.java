package com.teachbase.server.editor.application;

/**
 * 中文维护说明：同一 clientMutationId 只能描述一次确定的保存；换内容复用该键必须拒绝，避免把客户端错误伪装成成功重试。
 *
 * 英文术语对照：An idempotency key was reused with a different autosave request.
 */
public class EditorMutationConflictException extends RuntimeException {

    public EditorMutationConflictException() {
        super("editor_client_mutation_conflict");
    }
}
