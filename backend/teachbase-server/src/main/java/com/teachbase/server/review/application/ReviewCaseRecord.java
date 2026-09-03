package com.teachbase.server.review.application;

import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于人工审核模块的业务规则与事务编排层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Persistence-neutral view of one review case.
 */
public record ReviewCaseRecord(
        UUID reviewCaseId,
        UUID workspaceId,
        UUID questionId,
        UUID questionRevisionId,
        String expectedContentHash,
        String status,
        UUID assignedTo,
        OffsetDateTime openedAt,
        OffsetDateTime decidedAt) {
}
