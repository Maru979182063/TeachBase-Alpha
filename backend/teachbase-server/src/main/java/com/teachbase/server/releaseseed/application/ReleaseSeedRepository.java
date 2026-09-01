package com.teachbase.server.releaseseed.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Duration;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/** Persistence port restricted to loader checkpoints and package-domain mappings. */
public interface ReleaseSeedRepository {

    ReleaseSeedBatchLease acquire(
            UUID workspaceId,
            UUID actorUserId,
            UUID taxonomyVersionId,
            ValidatedReleaseSeedPackage seedPackage,
            Duration leaseDuration);

    void heartbeat(UUID batchId, UUID workerToken, Duration leaseDuration);

    void mapSourceDocument(
            UUID batchId,
            UUID workspaceId,
            String sourceDocumentKey,
            UUID sourceDocumentId,
            UUID fileVersionId,
            String assetSha256);

    void mapSourceRegion(
            UUID batchId,
            UUID workspaceId,
            String sourceRegionKey,
            String sourceDocumentKey,
            UUID sourceRegionId);

    Optional<ReleaseSeedSourceMapping> findSourceDocument(UUID batchId, String sourceDocumentKey);

    Optional<ReleaseSeedSourceMapping> findSourceRegion(UUID batchId, String sourceRegionKey);

    void recordApproved(
            UUID batchId,
            UUID workerToken,
            int itemIndex,
            ReleaseSeedItemResult result,
            Duration leaseDuration);

    Optional<UUID> findQuestionId(UUID batchId, String externalKey);

    void recordRelations(UUID batchId, UUID workerToken, int relationCount, Duration leaseDuration);

    ReleaseSeedBatchLease complete(UUID batchId, UUID workerToken);

    void fail(UUID batchId, UUID workerToken, String code);

    ReleaseSeedBatchLease find(UUID workspaceId, String packageContentHash);

    ReleaseSeedVerification verify(UUID batchId);
}
