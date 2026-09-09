package com.teachbase.server.standardmodule.api;

/** 中文维护说明：模块审核并发或状态冲突的稳定错误码载体。 */
public class StandardModuleReviewStateException extends RuntimeException {
    public StandardModuleReviewStateException(String message) {
        super(message);
    }
}
