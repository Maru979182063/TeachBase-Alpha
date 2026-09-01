package com.teachbase.server.question.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** Complete immutable revision used when a basket or editor freezes referenced content. */
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
