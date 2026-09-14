package com.teachbase.server.tagfeedback.application;

/**
 * 中文维护说明：表示客户端提交的标签集合、版本或上下文违反 01A 冻结合同。
 */
public class TagFeedbackValidationException extends RuntimeException {

    public TagFeedbackValidationException(String code) {
        super(code);
    }
}
