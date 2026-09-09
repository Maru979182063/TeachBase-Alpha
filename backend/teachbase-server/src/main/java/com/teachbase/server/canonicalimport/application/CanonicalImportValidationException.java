package com.teachbase.server.canonicalimport.application;

/** 中文维护说明：合同、依赖或恢复校验失败的稳定错误。 */
public class CanonicalImportValidationException extends RuntimeException {
    public CanonicalImportValidationException(String code) {
        super(code);
    }
}
