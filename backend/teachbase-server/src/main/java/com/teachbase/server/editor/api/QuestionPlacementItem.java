package com.teachbase.server.editor.api;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.util.UUID;

/** Display contract for one concrete question revision inserted into an editor draft. */
public record QuestionPlacementItem(
        @NotNull UUID questionRevisionId,
        @NotBlank String displayMode,
        boolean showAnswer,
        boolean showAnalysis) {
}
