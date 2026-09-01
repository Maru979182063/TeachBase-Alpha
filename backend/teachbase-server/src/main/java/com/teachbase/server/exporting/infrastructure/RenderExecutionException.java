package com.teachbase.server.exporting.infrastructure;

/**
 * 中文维护说明：本文件属于稳定导出与渲染队列模块的数据库或外部工具适配层，表达可识别的业务失败，错误码和重试语义属于对外合同。
 *
 * 英文术语对照：Structured renderer failure carrying retry policy into the durable queue.
 */
final class RenderExecutionException extends RuntimeException {

    private final String code;
    private final boolean retryable;

    RenderExecutionException(String code, boolean retryable) {
        super(code);
        this.code = code;
        this.retryable = retryable;
    }

    RenderExecutionException(String code, boolean retryable, Throwable cause) {
        super(code, cause);
        this.code = code;
        this.retryable = retryable;
    }

    String code() {
        return code;
    }

    boolean retryable() {
        return retryable;
    }
}
