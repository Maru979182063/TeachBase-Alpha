package com.teachbase.server.review.api;

import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于人工审核模块的对外稳定合同层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Stable HTTP representation of review workflow state.
 */
public record ReviewCaseResponse(
        UUID reviewCaseId,
        UUID questionId,
        UUID questionRevisionId,
        String expectedContentHash,
        String status,
        UUID assignedTo,
        OffsetDateTime openedAt,
        OffsetDateTime decidedAt) {
}
