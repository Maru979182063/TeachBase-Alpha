package com.teachbase.server.taxonomy.api;

import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Stable node identifier pinned to one taxonomy version.
 */
public record TaxonomyNodeResponse(
        UUID taxonomyNodeId,
        UUID taxonomyVersionId,
        String knowledgeCode,
        String displayName) {
}
