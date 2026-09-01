package com.teachbase.server.question.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：One complete, pre-database question packet produced by a protected pipeline.
 */
public record QuestionImportItem(
        @NotBlank @Size(max = 240) String externalKey,
        @NotBlank @Size(max = 80) String sourceSystem,
        @NotBlank @Size(max = 512) String sourceKey,
        @NotBlank String reviewStatus,
        @NotBlank @Size(max = 80) String subject,
        @Size(max = 80) String stage,
        @Size(max = 80) String grade,
        @NotBlank @Size(max = 80) String questionType,
        @Size(max = 512) String title,
        @Size(max = 512) String lesson,
        @Size(max = 512) String primaryKnowledgeTag,
        @NotNull JsonNode secondaryKnowledgeTags,
        Integer difficultyStars,
        String materialMarkdown,
        @NotBlank String stemMarkdown,
        @NotNull JsonNode options,
        String answerMarkdown,
        String analysisMarkdown,
        @NotNull JsonNode content,
        @NotNull JsonNode provenance,
        String contentHash,
        String sourcePayloadHash,
        String importEnvelopeHash) {
}
