package com.teachbase.server.question.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于题目、修订与检索模块的对外稳定合同层，封装跨层调用参数，不能用它绕过对应应用服务的校验。
 *
 * 英文术语对照：Idempotent source evidence link for one immutable question revision.
 */
public record QuestionSourceEvidenceCommand(
        UUID workspaceId,
        UUID questionId,
        UUID questionRevisionId,
        UUID sourceDocumentId,
        UUID sourceRegionId,
        String sourceLabel,
        Integer sourcePageStart,
        Integer sourcePageEnd,
        JsonNode sourceReference) {
}
