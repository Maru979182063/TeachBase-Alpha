package com.teachbase.server.tagfeedback.application;

/**
 * 中文维护说明：统一隐藏跨工作空间实体是否存在，避免通过错误信息枚举外部题目或知识树。
 */
public class TagFeedbackAccessException extends RuntimeException {

    public TagFeedbackAccessException() {
        super("TAG_FEEDBACK_ACCESS_DENIED");
    }
}
