package com.teachbase.server.question.api;

import java.util.UUID;

/** Identity and idempotency outcome for one imported source question. */
public record QuestionImportResult(
        UUID questionId,
        UUID questionRevisionId,
        long revisionNo,
        String reviewStatus,
        boolean createdQuestion,
        boolean createdRevision) {
}
