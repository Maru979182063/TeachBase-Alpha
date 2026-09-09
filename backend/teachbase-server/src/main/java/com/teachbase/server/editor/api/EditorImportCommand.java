package com.teachbase.server.editor.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** 中文维护说明：以稳定 importDocumentKey 创建或追加不可变 editor revision。 */
public record EditorImportCommand(
        UUID workspaceId,
        UUID actorUserId,
        String importDocumentKey,
        String documentKind,
        String title,
        int schemaVersion,
        JsonNode masterDoc,
        JsonNode versionOverrides) {
}
