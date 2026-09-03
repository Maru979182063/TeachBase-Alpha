package com.teachbase.server.question.api;

import java.util.List;

/**
 * 中文维护说明：本文件属于题目、修订与检索模块的对外稳定合同层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Ordered import outcomes corresponding one-for-one with the request batch.
 */
public record BulkQuestionImportResponse(List<QuestionImportResult> results) {
}
