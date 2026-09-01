package com.teachbase.server.question.api;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于题目、修订与检索模块的对外稳定合同层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Bounded transactional import request; clients split larger ingestion runs into batches.
 */
public record BulkQuestionImportRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotEmpty @Size(max = 500) List<@Valid QuestionImportItem> questions) {
}
