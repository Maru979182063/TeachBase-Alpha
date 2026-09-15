package com.teachbase.server.governanceprojection.application;

/** 中文维护说明：仅用于稳定的治理投影请求错误码，不泄漏数据库异常文本。 */
public class GovernanceProjectionValidationException extends RuntimeException {
    public GovernanceProjectionValidationException(String code) {
        super(code);
    }
}
