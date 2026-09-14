package com.teachbase.server.difficultyfeedback.application;

/** 中文维护说明：调用者缺少工作空间角色或对应教学范围。 */
public class DifficultyFeedbackAccessException extends RuntimeException {
    public DifficultyFeedbackAccessException() {
        super("DIFFICULTY_FEEDBACK_ACCESS_DENIED");
    }
}
