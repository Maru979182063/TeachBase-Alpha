package com.teachbase.server.question.api;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.UUID;

/** Bounded transactional import request; clients split larger ingestion runs into batches. */
public record BulkQuestionImportRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotEmpty @Size(max = 500) List<@Valid QuestionImportItem> questions) {
}
