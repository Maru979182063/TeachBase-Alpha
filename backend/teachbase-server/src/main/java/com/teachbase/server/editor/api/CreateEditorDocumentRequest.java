package com.teachbase.server.editor.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/** Initial canonical Tiptap document and optional complete variant overrides. */
public record CreateEditorDocumentRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotBlank String documentKind,
        @NotBlank @Size(max = 512) String title,
        int schemaVersion,
        @NotNull JsonNode masterDoc,
        @NotNull JsonNode versionOverrides) {
}
