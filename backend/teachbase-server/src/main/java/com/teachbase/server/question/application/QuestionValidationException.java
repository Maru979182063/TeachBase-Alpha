package com.teachbase.server.question.application;

/**
 * 中文维护说明：本文件属于题目、修订与检索模块的业务规则与事务编排层，表达可识别的业务失败，错误码和重试语义属于对外合同。
 *
 * 英文术语对照：Stable machine-readable validation failure returned by the question API.
 */
public class QuestionValidationException extends RuntimeException {

    public QuestionValidationException(String code) {
        super(code);
    }
}
