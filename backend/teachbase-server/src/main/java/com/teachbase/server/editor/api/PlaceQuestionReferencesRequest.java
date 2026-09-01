package com.teachbase.server.editor.api;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.UUID;

/** Batch placement creates one editor revision regardless of the number of questions. */
public record PlaceQuestionReferencesRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        long expectedRevisionNo,
        int insertionIndex,
        @NotEmpty List<String> targetLayers,
        @NotEmpty @Size(max = 200) List<@Valid QuestionPlacementItem> questions) {
}
