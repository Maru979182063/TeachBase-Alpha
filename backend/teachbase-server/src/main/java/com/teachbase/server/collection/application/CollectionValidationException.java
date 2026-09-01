package com.teachbase.server.collection.application;

/**
 * 中文维护说明：本文件属于题篮与快照模块的业务规则与事务编排层，表达可识别的业务失败，错误码和重试语义属于对外合同。
 *
 * 英文术语对照：Stable machine-readable collection request failure.
 */
public class CollectionValidationException extends RuntimeException {

    public CollectionValidationException(String code) {
        super(code);
    }
}
