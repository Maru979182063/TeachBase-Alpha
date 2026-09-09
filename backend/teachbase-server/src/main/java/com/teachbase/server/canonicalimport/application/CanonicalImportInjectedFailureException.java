package com.teachbase.server.canonicalimport.application;

/** 中文维护说明：仅测试开关可触发的可控中断，生产配置下永远不可用。 */
class CanonicalImportInjectedFailureException extends RuntimeException {
    CanonicalImportInjectedFailureException(String code) {
        super(code);
    }
}
