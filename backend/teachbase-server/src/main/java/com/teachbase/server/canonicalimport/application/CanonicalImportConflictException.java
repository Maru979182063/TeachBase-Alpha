package com.teachbase.server.canonicalimport.application;

/** 中文维护说明：稳定 package key、lease 或 frozen payload 冲突统一映射为 409。 */
public class CanonicalImportConflictException extends RuntimeException {
    public CanonicalImportConflictException(String code) {
        super(code);
    }
}
