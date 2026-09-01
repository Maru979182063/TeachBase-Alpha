package com.teachbase.server.taxonomy.application;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，表达可识别的业务失败，错误码和重试语义属于对外合同。
 *
 * 英文术语对照：Stable taxonomy validation or lifecycle error.
 */
public class TaxonomyValidationException extends RuntimeException {

    public TaxonomyValidationException(String code) {
        super(code);
    }
}
