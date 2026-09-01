package com.teachbase.server.fileasset.domain;

/**
 * 中文维护说明：本文件属于文件资产模块的领域值对象层，表达可识别的业务失败，错误码和重试语义属于对外合同。
 *
 * 英文术语对照：Stable file-domain validation failure for client-visible problem details.
 */
public class DomainValidationException extends IllegalArgumentException {

    public DomainValidationException(String message) {
        super(message);
    }
}
