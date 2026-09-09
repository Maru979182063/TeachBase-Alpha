package com.teachbase.server.handout.application;

import com.teachbase.server.handout.api.EditorRevisionArtifactInput;
import com.teachbase.server.handout.api.HandoutCompositionResponse;
import java.util.List;
import java.util.UUID;

/** 中文维护说明：不可变 edition、occurrence、source evidence 与 artifact 的持久化端口。 */
public interface HandoutCompositionRepository {
    HandoutCompositionResponse create(
            UUID workspaceId,
            UUID actorUserId,
            UUID editorDocumentId,
            UUID editorRevisionId,
            List<ResolvedHandoutEdition> editions,
            List<EditorRevisionArtifactInput> artifacts);
}
