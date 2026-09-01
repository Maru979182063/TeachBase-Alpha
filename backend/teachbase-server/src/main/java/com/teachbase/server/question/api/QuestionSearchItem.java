package com.teachbase.server.question.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.OffsetDateTime;
import java.util.UUID;

/** Compact approved question projection used by search and placement interfaces. */
public record QuestionSearchItem(
        UUID questionId,
        UUID questionRevisionId,
        String externalKey,
        String reviewStatus,
        String subject,
        String stage,
        String grade,
        String questionType,
        String title,
        String primaryKnowledgeTag,
        Integer difficultyStars,
        String stemMarkdown,
        JsonNode provenance,
        boolean humanReviewed,
        boolean referenced,
        OffsetDateTime approvedAt,
        OffsetDateTime revisionCreatedAt) {
}
