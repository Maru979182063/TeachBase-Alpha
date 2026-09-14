package com.teachbase.server.difficultyfeedback.application;

/** 中文维护说明：对外统一隐藏跨 workspace 实体是否存在。 */
public class DifficultyFeedbackNotFoundException extends RuntimeException {
    public DifficultyFeedbackNotFoundException(String code) {
        super(code);
    }
}
