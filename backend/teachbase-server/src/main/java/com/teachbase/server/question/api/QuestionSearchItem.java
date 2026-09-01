package com.teachbase.server.question.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Compact approved question projection used by search and placement interfaces.
 */
public record QuestionSearchItem(
        UUID questionId,
        UUID questionRevisionId,
        String externalKey,
        String reviewStatus,
        String subject,
        String stage,
        String grade,
        String questionType,
        String title,
        String primaryKnowledgeTag,
        Integer difficultyStars,
        String stemMarkdown,
        JsonNode provenance,
        boolean humanReviewed,
        boolean referenced,
        OffsetDateTime approvedAt,
        OffsetDateTime revisionCreatedAt) {
}
