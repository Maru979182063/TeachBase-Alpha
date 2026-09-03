package com.teachbase.server.identity.application;

/**
 * 教学范围重复、主范围冲突或越权修改时使用的稳定业务异常。
 */
public class TeachingScopeValidationException extends RuntimeException {

    public TeachingScopeValidationException(String code) {
        super(code);
    }
}
