package com.teachbase.server.taxonomy.api;

import java.util.UUID;

/**
 * 中文维护说明：本文件属于知识体系版本模块的对外稳定合同层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Identifier returned after an idempotent question-to-node assignment.
 */
public record QuestionTaxonomyLinkResponse(
        UUID questionTaxonomyLinkId,
        UUID questionRevisionId,
        UUID taxonomyNodeId,
        String relationType) {
}
