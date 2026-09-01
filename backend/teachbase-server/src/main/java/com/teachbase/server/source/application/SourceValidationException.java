package com.teachbase.server.source.application;

/**
 * 中文维护说明：本文件属于题源证据模块的业务规则与事务编排层，表达可识别的业务失败，错误码和重试语义属于对外合同。
 *
 * 英文术语对照：Stable source evidence validation failure.
 */
public class SourceValidationException extends RuntimeException {

    public SourceValidationException(String code) {
        super(code);
    }
}
