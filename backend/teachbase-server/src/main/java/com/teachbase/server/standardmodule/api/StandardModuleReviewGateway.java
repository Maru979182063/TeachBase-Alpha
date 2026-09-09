package com.teachbase.server.standardmodule.api;

import java.util.Optional;
import java.util.UUID;

/** 中文维护说明：Review 对模块审核状态的窄接口，审核决定不得修改模块正文。 */
public interface StandardModuleReviewGateway {
    Optional<StandardModuleReviewTarget> findTarget(UUID workspaceId, UUID standardModuleRevisionId);

    void applyDecision(
            UUID workspaceId,
            UUID actorUserId,
            UUID standardModuleRevisionId,
            String expectedContentHash,
            String decision);
}
