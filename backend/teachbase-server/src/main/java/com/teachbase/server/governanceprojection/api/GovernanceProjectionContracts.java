package com.teachbase.server.governanceprojection.api;

import jakarta.validation.constraints.NotNull;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

/** 中文维护说明：这是最小治理查询、重建与健康检查合同，不承诺全文搜索或推荐语义。 */
public final class GovernanceProjectionContracts {

    private GovernanceProjectionContracts() {
    }

    public record TagProjectionView(
            String taxonomyKey,
            UUID taxonomyVersionId,
            UUID currentSnapshotId,
            UUID primaryNodeId,
            List<UUID> secondaryNodeIds,
            String decisionSource,
            String status,
            long authorityStateVersion,
            String labelSetHash,
            String projectionSemanticHash) {
    }

    public record DifficultyProjectionView(
            String rubricKey,
            UUID rubricVersionId,
            String contextKey,
            Integer difficultyValue,
            String decisionSource,
            String status,
            long authorityStateVersion,
            String projectionSemanticHash) {
    }

    public record GovernanceQueryItem(
            UUID questionRevisionId,
            List<TagProjectionView> tags,
            List<DifficultyProjectionView> difficulties) {
    }

    public record GovernanceQueryResponse(
            List<GovernanceQueryItem> items,
            int limit,
            String nextCursor) {
    }

    public record RebuildRequest(@NotNull UUID actorUserId, UUID workspaceId) {
    }

    public record RebuildResponse(
            int workspaceCount,
            int tagProjectionCount,
            int difficultyProjectionCount) {
    }

    public record ProjectionHealthResponse(
            UUID workspaceId,
            long pendingEventCount,
            long failedEventCount,
            Long oldestPendingAgeSeconds,
            OffsetDateTime lastSuccessfulProjectionAt,
            long tagLagCount,
            long difficultyLagCount) {
    }
}
