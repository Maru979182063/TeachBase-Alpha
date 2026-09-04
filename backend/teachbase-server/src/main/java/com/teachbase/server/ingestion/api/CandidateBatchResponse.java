package com.teachbase.server.ingestion.api;

import com.teachbase.server.question.api.QuestionImportResult;
import com.teachbase.server.review.api.ReviewCaseResponse;
import java.util.List;
import java.util.UUID;

/** 中文维护说明：回执返回实际数据库身份；审核终态的历史重放不重新打开审核任务。 */
public record CandidateBatchResponse(UUID sourceDocumentId, List<Item> results) {
    /** 中文维护说明：每项绑定不可变题目修订、题源区域及可选的开放审核任务。 */
    public record Item(QuestionImportResult question, UUID sourceRegionId, ReviewCaseResponse reviewCase) {
    }
}
