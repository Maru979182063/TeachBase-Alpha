package com.teachbase.server.difficultyfeedback.application;

/** 中文维护说明：难度反馈请求违反冻结领域合同。 */
public class DifficultyFeedbackValidationException extends RuntimeException {
    public DifficultyFeedbackValidationException(String code) {
        super(code);
    }
}
