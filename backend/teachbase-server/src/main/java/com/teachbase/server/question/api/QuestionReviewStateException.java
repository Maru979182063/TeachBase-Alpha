package com.teachbase.server.question.api;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，表达可识别的业务失败，错误码和重试语义属于对外合同。
 *
 * 英文术语对照：Review target changed, disappeared, or was already decided.
 */
public class QuestionReviewStateException extends RuntimeException {

    public QuestionReviewStateException(String code) {
        super(code);
    }
}
