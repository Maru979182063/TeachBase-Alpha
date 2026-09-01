package com.teachbase.server.exporting.infrastructure;

/** Structured renderer failure carrying retry policy into the durable queue. */
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
