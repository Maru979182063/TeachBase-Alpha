package com.teachbase.server.question.application;

import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于题目、修订与检索模块的业务规则与事务编排层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Decoded keyset cursor matching revision-created-desc/question-id-asc ordering.
 */
public record QuestionSearchCursor(OffsetDateTime revisionCreatedAt, UUID questionId) {
}
