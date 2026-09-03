package com.teachbase.server.question.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于题目、修订与检索模块的对外稳定合同层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Complete immutable revision used when a basket or editor freezes referenced content.
 */
public record QuestionRevisionDescriptor(
        UUID questionId,
        UUID questionRevisionId,
        long revisionNo,
        String reviewStatus,
        String subject,
        String stage,
        String grade,
        String questionType,
        String title,
        String materialMarkdown,
        String stemMarkdown,
        JsonNode options,
        String answerMarkdown,
        String analysisMarkdown,
        JsonNode content,
        JsonNode provenance,
        String contentHash) {
}
