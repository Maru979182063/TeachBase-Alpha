package com.teachbase.server.governanceprojection.application;

import static com.teachbase.server.governanceprojection.api.GovernanceProjectionContracts.*;
import static com.teachbase.server.governanceprojection.application.GovernanceProjectionHasher.*;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/** 中文维护说明：持久化端口按租约事件和完整投影写入划分，禁止暴露事实层修改能力。 */
public interface GovernanceProjectionRepository {

    Optional<ClaimedEvent> claimNext(String workerId, OffsetDateTime now, OffsetDateTime leaseUntil);

    Optional<ClaimedEvent> lockClaim(UUID eventId, String workerId, OffsetDateTime now);

    Optional<TagAuthority> loadTagAuthority(UUID stateId, boolean lock);

    Optional<DifficultyAuthority> loadDifficultyAuthority(UUID stateId, boolean lock);

    void upsertTag(TagAuthority authority, UUID projectionId, String semanticHash, OffsetDateTime projectedAt);

    void upsertDifficulty(
            DifficultyAuthority authority, UUID projectionId, String semanticHash, OffsetDateTime projectedAt);

    void markProcessed(UUID eventId, String workerId, OffsetDateTime processedAt);

    void markFailed(UUID eventId, String workerId, OffsetDateTime availableAt, String errorCode);

    List<UUID> lockTagStateIds(UUID workspaceId);

    List<UUID> lockDifficultyStateIds(UUID workspaceId);

    void clearWorkspace(UUID workspaceId);

    List<UUID> maintenanceWorkspaces(UUID actorUserId, UUID requestedWorkspaceId);

    List<UUID> queryQuestionRevisionIds(GovernanceQuery query, UUID cursor, int fetchLimit);

    List<TagProjectionView> findTagProjections(UUID workspaceId, UUID questionRevisionId);

    List<DifficultyProjectionView> findDifficultyProjections(UUID workspaceId, UUID questionRevisionId);

    ProjectionHealthResponse health(UUID workspaceId, OffsetDateTime now);

    record ClaimedEvent(
            UUID eventId, UUID workspaceId, UUID questionRevisionId, String domain,
            UUID authorityStateId, long authorityStateVersion, String eventKey,
            int attemptCount, String workerId) {
    }

    record GovernanceQuery(
            UUID workspaceId, String subject, String stage, String taxonomyKey,
            UUID primaryTagId, UUID secondaryTagId, String rubricKey,
            String difficultyContextKey, Integer difficultyValue) {
    }
}
