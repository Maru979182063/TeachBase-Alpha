package com.teachbase.server.handout.api;

import java.util.List;
import java.util.UUID;

/** 中文维护说明：composition 创建结果及可审计计数，不将关系重新压回匿名 master JSON。 */
public record HandoutCompositionResponse(
        UUID editorDocumentId,
        UUID editorRevisionId,
        UUID workspaceId,
        List<HandoutEditionResult> editions,
        int artifactCount) {
}
