package com.teachbase.server.question.api;

import java.util.UUID;

/**
 * 中文维护说明：本文件属于题目、修订与检索模块的对外稳定合同层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Immutable question revision facts exposed to the review module.
 */
public record QuestionReviewTarget(
        UUID questionId,
        UUID questionRevisionId,
        String reviewStatus,
        String contentHash) {
}
