package com.teachbase.server.question.api;

import java.util.UUID;

/** Stable graph edge between two question identities. */
public record QuestionRelationCommand(
        UUID workspaceId,
        UUID parentQuestionId,
        UUID childQuestionId,
        String relationType,
        int sortOrder) {
}
