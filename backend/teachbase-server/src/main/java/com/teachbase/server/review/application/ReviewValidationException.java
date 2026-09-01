package com.teachbase.server.review.application;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，表达可识别的业务失败，错误码和重试语义属于对外合同。
 *
 * 英文术语对照：Stable validation or optimistic-state error returned by Review HTTP APIs.
 */
public class ReviewValidationException extends RuntimeException {

    public ReviewValidationException(String code) {
        super(code);
    }
}
