package com.teachbase.server.editor.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import java.util.UUID;

/** Optimistic full-document save request based on an expected current revision. */
public record UpdateEditorDraftRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @Positive long expectedRevisionNo,
        int schemaVersion,
        @NotNull JsonNode masterDoc,
        @NotNull JsonNode versionOverrides) {
}
