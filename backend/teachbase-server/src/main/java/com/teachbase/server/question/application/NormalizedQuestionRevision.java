package com.teachbase.server.question.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** Validated canonical form passed to persistence; JSON strings match the hashed nodes. */
public record NormalizedQuestionRevision(
        UUID workspaceId,
        UUID actorUserId,
        String externalKey,
        String sourceSystem,
        String sourceKey,
        String reviewStatus,
        String subject,
        String stage,
        String grade,
        String questionType,
        String title,
        String lesson,
        String primaryKnowledgeTag,
        JsonNode secondaryKnowledgeTags,
        Integer difficultyStars,
        String materialMarkdown,
        String stemMarkdown,
        JsonNode options,
        String answerMarkdown,
        String analysisMarkdown,
        JsonNode content,
        JsonNode provenance,
        String contentHash,
        String sourcePayloadHash,
        String importEnvelopeHash) {
}
