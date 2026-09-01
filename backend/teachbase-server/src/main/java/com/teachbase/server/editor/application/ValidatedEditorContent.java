package com.teachbase.server.editor.application;

import com.fasterxml.jackson.databind.JsonNode;

/** Canonical JSON strings and deterministic hash produced by editor validation. */
public record ValidatedEditorContent(
        int schemaVersion,
        JsonNode masterDoc,
        JsonNode versionOverrides,
        String masterDocJson,
        String versionOverridesJson,
        String contentHash) {
}
