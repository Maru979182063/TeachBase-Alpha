package com.teachbase.server.releaseseed.application;

/**
 * 中文维护说明：本文件属于首发数据包导入模块的业务规则与事务编排层，表达可识别的业务失败，错误码和重试语义属于对外合同。
 *
 * 英文术语对照：Stable fail-closed package, mapping, or checkpoint validation error.
 */
public class ReleaseSeedValidationException extends RuntimeException {

    public ReleaseSeedValidationException(String code) {
        super(code);
    }

    public ReleaseSeedValidationException(String code, Throwable cause) {
        super(code, cause);
    }
}
