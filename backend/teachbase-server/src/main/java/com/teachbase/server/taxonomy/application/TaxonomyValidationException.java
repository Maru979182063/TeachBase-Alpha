package com.teachbase.server.taxonomy.application;

/**
 * 中文维护说明：本文件属于知识体系版本模块的业务规则与事务编排层，表达可识别的业务失败，错误码和重试语义属于对外合同。
 *
 * 英文术语对照：Stable taxonomy validation or lifecycle error.
 */
public class TaxonomyValidationException extends RuntimeException {

    public TaxonomyValidationException(String code) {
        super(code);
    }
}
