package com.teachbase.server.question.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** Idempotent source evidence link for one immutable question revision. */
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
