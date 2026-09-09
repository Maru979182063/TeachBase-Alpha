package com.teachbase.server.standardmodule.application;

/** 中文维护说明：标准模块输入、引用或状态不满足合同的稳定业务异常。 */
public class StandardModuleValidationException extends IllegalArgumentException {
    public StandardModuleValidationException(String message) {
        super(message);
    }
}
