package com.teachbase.server.tagfeedback.application;

/**
 * 中文维护说明：仅在调用方已通过当前 workspace 业务权限校验后返回本工作空间内的资源缺失。
 */
public class TagFeedbackNotFoundException extends RuntimeException {

    public TagFeedbackNotFoundException(String code) {
        super(code);
    }
}
