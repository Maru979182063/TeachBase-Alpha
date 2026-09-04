package com.teachbase.server.ingestion.application;

/** 中文维护说明：只承载结构合同错误，不用代码规则判断教学内容是否正确。 */
public class CandidateValidationException extends RuntimeException {
    public CandidateValidationException(String code) {
        super(code);
    }
}
