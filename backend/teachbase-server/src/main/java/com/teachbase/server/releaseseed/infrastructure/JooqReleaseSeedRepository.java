package com.teachbase.server.releaseseed.infrastructure;

import static com.teachbase.jooq.tables.QuestionRevision.QUESTION_REVISION;
import static com.teachbase.jooq.tables.QuestionTaxonomyLink.QUESTION_TAXONOMY_LINK;
import static com.teachbase.jooq.tables.ReleaseSeedBatch.RELEASE_SEED_BATCH;
import static com.teachbase.jooq.tables.ReleaseSeedItem.RELEASE_SEED_ITEM;
import static com.teachbase.jooq.tables.ReleaseSeedSourceDocumentMap.RELEASE_SEED_SOURCE_DOCUMENT_MAP;
import static com.teachbase.jooq.tables.ReleaseSeedSourceRegionMap.RELEASE_SEED_SOURCE_REGION_MAP;
import static com.teachbase.jooq.tables.ReviewDecision.REVIEW_DECISION;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.teachbase.server.releaseseed.application.ReleaseSeedBatchLease;
import com.teachbase.server.releaseseed.application.ReleaseSeedItemResult;
import com.teachbase.server.releaseseed.application.ReleaseSeedRepository;
import com.teachbase.server.releaseseed.application.ReleaseSeedSourceMapping;
import com.teachbase.server.releaseseed.application.ReleaseSeedValidationException;
import com.teachbase.server.releaseseed.application.ReleaseSeedVerification;
import com.teachbase.server.releaseseed.application.ValidatedReleaseSeedPackage;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.Optional;
import java.util.UUID;
import org.jooq.DSLContext;
import org.jooq.JSON;
import org.jooq.impl.DSL;
import org.springframework.stereotype.Repository;

/**
 * 中文维护说明：本文件属于首发数据包导入模块的数据库或外部工具适配层，负责落实持久化合同；并发正确性最终由事务、锁和数据库约束共同保证。
 *
 * 英文术语对照：jOOQ checkpoint ledger with expiring process leases and monotonic item cursors.
 */
@Repository
class JooqReleaseSeedRepository implements ReleaseSeedRepository {

    private final DSLContext database;
    private final ObjectMapper objectMapper;

    JooqReleaseSeedRepository(DSLContext database, ObjectMapper objectMapper) {
        this.database = database;
        this.objectMapper = objectMapper;
    }

    @Override
    public ReleaseSeedBatchLease acquire(
            UUID workspaceId,
            UUID actorUserId,
            UUID taxonomyVersionId,
            ValidatedReleaseSeedPackage seedPackage,
            Duration leaseDuration) {
        OffsetDateTime now = OffsetDateTime.now();
        var stored = database.selectFrom(RELEASE_SEED_BATCH)
                .where(RELEASE_SEED_BATCH.WORKSPACE_ID.eq(workspaceId))
                .and(RELEASE_SEED_BATCH.PACKAGE_CONTENT_HASH.eq(seedPackage.packageContentHash()))
                .forUpdate()
                .fetchOne();
        if (stored == null) {
            UUID batchId = UUID.randomUUID();
            ObjectNode metadata = objectMapper.createObjectNode();
            metadata.put("schemaVersion", seedPackage.manifest().path("schemaVersion").asText());
            metadata.put("reviewPolicyVersion", seedPackage.manifest().path("reviewPolicyVersion").asText());
            database.insertInto(RELEASE_SEED_BATCH)
                    .set(RELEASE_SEED_BATCH.RELEASE_SEED_BATCH_ID, batchId)
                    .set(RELEASE_SEED_BATCH.WORKSPACE_ID, workspaceId)
                    .set(RELEASE_SEED_BATCH.PACKAGE_BATCH_ID, seedPackage.batchId())
                    .set(RELEASE_SEED_BATCH.RELEASE_VERSION, seedPackage.releaseVersion())
                    .set(RELEASE_SEED_BATCH.PACKAGE_CONTENT_HASH, seedPackage.packageContentHash())
                    .set(RELEASE_SEED_BATCH.TAXONOMY_VERSION_ID, taxonomyVersionId)
                    .set(RELEASE_SEED_BATCH.STATUS, "validated")
                    .set(RELEASE_SEED_BATCH.QUESTION_COUNT, seedPackage.questions().size())
                    .set(RELEASE_SEED_BATCH.REJECTED_COUNT, seedPackage.rejectedQuestions().size())
                    .set(RELEASE_SEED_BATCH.PACKAGE_METADATA_JSON, json(metadata))
                    .set(RELEASE_SEED_BATCH.STARTED_BY, actorUserId)
                    .execute();
            for (int index = 0; index < seedPackage.questions().size(); index++) {
                JsonNode question = seedPackage.questions().get(index);
                database.insertInto(RELEASE_SEED_ITEM)
                        .set(RELEASE_SEED_ITEM.RELEASE_SEED_BATCH_ID, batchId)
                        .set(RELEASE_SEED_ITEM.WORKSPACE_ID, workspaceId)
                        .set(RELEASE_SEED_ITEM.ITEM_INDEX, index)
                        .set(RELEASE_SEED_ITEM.EXTERNAL_KEY, question.path("externalKey").asText())
                        .set(RELEASE_SEED_ITEM.SOURCE_SYSTEM, question.path("sourceSystem").asText())
                        .set(RELEASE_SEED_ITEM.SOURCE_KEY, question.path("sourceKey").asText())
                        .set(RELEASE_SEED_ITEM.DECLARED_CONTENT_HASH, question.path("contentHash").asText())
                        .set(RELEASE_SEED_ITEM.STATUS, "pending")
                        .execute();
            }
            stored = database.selectFrom(RELEASE_SEED_BATCH)
                    .where(RELEASE_SEED_BATCH.RELEASE_SEED_BATCH_ID.eq(batchId))
                    .forUpdate()
                    .fetchOne();
        }
        if (!stored.getTaxonomyVersionId().equals(taxonomyVersionId)
                || !stored.getPackageBatchId().equals(seedPackage.batchId())
                || !stored.getReleaseVersion().equals(seedPackage.releaseVersion())
                || stored.getQuestionCount() != seedPackage.questions().size()) {
            throw new ReleaseSeedValidationException("release_seed_batch_identity_conflict");
        }
        if (stored.getStatus().equals("completed")) return map(stored);
        if (stored.getStatus().equals("importing")
                && stored.getLeaseExpiresAt() != null
                && stored.getLeaseExpiresAt().isAfter(now)) {
            throw new ReleaseSeedValidationException("release_seed_batch_lease_busy");
        }
        UUID workerToken = UUID.randomUUID();
        database.update(RELEASE_SEED_BATCH)
                .set(RELEASE_SEED_BATCH.STATUS, "importing")
                .set(RELEASE_SEED_BATCH.WORKER_TOKEN, workerToken)
                .set(RELEASE_SEED_BATCH.LEASE_EXPIRES_AT, now.plus(leaseDuration))
                .set(RELEASE_SEED_BATCH.ATTEMPT_NO, stored.getAttemptNo() + 1)
                .setNull(RELEASE_SEED_BATCH.LAST_ERROR_JSON)
                .set(RELEASE_SEED_BATCH.UPDATED_AT, now)
                .where(RELEASE_SEED_BATCH.RELEASE_SEED_BATCH_ID.eq(stored.getReleaseSeedBatchId()))
                .execute();
        return findById(stored.getReleaseSeedBatchId());
    }

    @Override
    public void heartbeat(UUID batchId, UUID workerToken, Duration leaseDuration) {
        OffsetDateTime now = OffsetDateTime.now();
        int changed = database.update(RELEASE_SEED_BATCH)
                .set(RELEASE_SEED_BATCH.LEASE_EXPIRES_AT, now.plus(leaseDuration))
                .set(RELEASE_SEED_BATCH.UPDATED_AT, now)
                .where(RELEASE_SEED_BATCH.RELEASE_SEED_BATCH_ID.eq(batchId))
                .and(RELEASE_SEED_BATCH.WORKER_TOKEN.eq(workerToken))
                .and(RELEASE_SEED_BATCH.STATUS.eq("importing"))
                .execute();
        if (changed != 1) throw new ReleaseSeedValidationException("release_seed_batch_lease_lost");
    }

    @Override
    public void mapSourceDocument(
            UUID batchId,
            UUID workspaceId,
            String sourceDocumentKey,
            UUID sourceDocumentId,
            UUID fileVersionId,
            String assetSha256) {
        database.insertInto(RELEASE_SEED_SOURCE_DOCUMENT_MAP)
                .set(RELEASE_SEED_SOURCE_DOCUMENT_MAP.RELEASE_SEED_BATCH_ID, batchId)
                .set(RELEASE_SEED_SOURCE_DOCUMENT_MAP.WORKSPACE_ID, workspaceId)
                .set(RELEASE_SEED_SOURCE_DOCUMENT_MAP.SOURCE_DOCUMENT_KEY, sourceDocumentKey)
                .set(RELEASE_SEED_SOURCE_DOCUMENT_MAP.SOURCE_DOCUMENT_ID, sourceDocumentId)
                .set(RELEASE_SEED_SOURCE_DOCUMENT_MAP.FILE_VERSION_ID, fileVersionId)
                .set(RELEASE_SEED_SOURCE_DOCUMENT_MAP.ASSET_SHA256, assetSha256)
                .onConflict(
                        RELEASE_SEED_SOURCE_DOCUMENT_MAP.RELEASE_SEED_BATCH_ID,
                        RELEASE_SEED_SOURCE_DOCUMENT_MAP.SOURCE_DOCUMENT_KEY)
                .doNothing()
                .execute();
    }

    @Override
    public void mapSourceRegion(
            UUID batchId,
            UUID workspaceId,
            String sourceRegionKey,
            String sourceDocumentKey,
            UUID sourceRegionId) {
        database.insertInto(RELEASE_SEED_SOURCE_REGION_MAP)
                .set(RELEASE_SEED_SOURCE_REGION_MAP.RELEASE_SEED_BATCH_ID, batchId)
                .set(RELEASE_SEED_SOURCE_REGION_MAP.WORKSPACE_ID, workspaceId)
                .set(RELEASE_SEED_SOURCE_REGION_MAP.SOURCE_REGION_KEY, sourceRegionKey)
                .set(RELEASE_SEED_SOURCE_REGION_MAP.SOURCE_DOCUMENT_KEY, sourceDocumentKey)
                .set(RELEASE_SEED_SOURCE_REGION_MAP.SOURCE_REGION_ID, sourceRegionId)
                .onConflict(
                        RELEASE_SEED_SOURCE_REGION_MAP.RELEASE_SEED_BATCH_ID,
                        RELEASE_SEED_SOURCE_REGION_MAP.SOURCE_REGION_KEY)
                .doNothing()
                .execute();
    }

    @Override
    public Optional<ReleaseSeedSourceMapping> findSourceDocument(UUID batchId, String sourceDocumentKey) {
        return database.selectFrom(RELEASE_SEED_SOURCE_DOCUMENT_MAP)
                .where(RELEASE_SEED_SOURCE_DOCUMENT_MAP.RELEASE_SEED_BATCH_ID.eq(batchId))
                .and(RELEASE_SEED_SOURCE_DOCUMENT_MAP.SOURCE_DOCUMENT_KEY.eq(sourceDocumentKey))
                .fetchOptional(record -> new ReleaseSeedSourceMapping(
                        record.getSourceDocumentKey(), record.getSourceDocumentId(), null, record.getFileVersionId()));
    }

    @Override
    public Optional<ReleaseSeedSourceMapping> findSourceRegion(UUID batchId, String sourceRegionKey) {
        return database.selectFrom(RELEASE_SEED_SOURCE_REGION_MAP)
                .where(RELEASE_SEED_SOURCE_REGION_MAP.RELEASE_SEED_BATCH_ID.eq(batchId))
                .and(RELEASE_SEED_SOURCE_REGION_MAP.SOURCE_REGION_KEY.eq(sourceRegionKey))
                .fetchOptional(record -> new ReleaseSeedSourceMapping(
                        record.getSourceDocumentKey(), null, record.getSourceRegionId(), null));
    }

    @Override
    public void recordApproved(
            UUID batchId,
            UUID workerToken,
            int itemIndex,
            ReleaseSeedItemResult result,
            Duration leaseDuration) {
        OffsetDateTime now = OffsetDateTime.now();
        int itemChanged = database.update(RELEASE_SEED_ITEM)
                .set(RELEASE_SEED_ITEM.QUESTION_ID, result.questionId())
                .set(RELEASE_SEED_ITEM.QUESTION_REVISION_ID, result.questionRevisionId())
                .set(RELEASE_SEED_ITEM.REVIEW_CASE_ID, result.reviewCaseId())
                .set(RELEASE_SEED_ITEM.STATUS, "approved")
                .set(RELEASE_SEED_ITEM.CREATED_QUESTION, result.createdQuestion())
                .set(RELEASE_SEED_ITEM.CREATED_REVISION, result.createdRevision())
                .set(RELEASE_SEED_ITEM.PROCESSED_AT, now)
                .where(RELEASE_SEED_ITEM.RELEASE_SEED_BATCH_ID.eq(batchId))
                .and(RELEASE_SEED_ITEM.ITEM_INDEX.eq(itemIndex))
                .and(RELEASE_SEED_ITEM.STATUS.eq("pending"))
                .execute();
        if (itemChanged != 1) throw new ReleaseSeedValidationException("release_seed_item_checkpoint_conflict");
        int batchChanged = database.update(RELEASE_SEED_BATCH)
                .set(RELEASE_SEED_BATCH.NEXT_QUESTION_INDEX, itemIndex + 1)
                .set(RELEASE_SEED_BATCH.IMPORTED_COUNT,
                        RELEASE_SEED_BATCH.IMPORTED_COUNT.plus(result.createdRevision() ? 1 : 0))
                .set(RELEASE_SEED_BATCH.REUSED_COUNT,
                        RELEASE_SEED_BATCH.REUSED_COUNT.plus(result.createdRevision() ? 0 : 1))
                .set(RELEASE_SEED_BATCH.APPROVED_COUNT, RELEASE_SEED_BATCH.APPROVED_COUNT.plus(1))
                .set(RELEASE_SEED_BATCH.LEASE_EXPIRES_AT, now.plus(leaseDuration))
                .set(RELEASE_SEED_BATCH.UPDATED_AT, now)
                .where(RELEASE_SEED_BATCH.RELEASE_SEED_BATCH_ID.eq(batchId))
                .and(RELEASE_SEED_BATCH.WORKER_TOKEN.eq(workerToken))
                .and(RELEASE_SEED_BATCH.NEXT_QUESTION_INDEX.eq(itemIndex))
                .execute();
        if (batchChanged != 1) throw new ReleaseSeedValidationException("release_seed_cursor_checkpoint_conflict");
    }

    @Override
    public Optional<UUID> findQuestionId(UUID batchId, String externalKey) {
        return database.select(RELEASE_SEED_ITEM.QUESTION_ID)
                .from(RELEASE_SEED_ITEM)
                .where(RELEASE_SEED_ITEM.RELEASE_SEED_BATCH_ID.eq(batchId))
                .and(RELEASE_SEED_ITEM.EXTERNAL_KEY.eq(externalKey))
                .and(RELEASE_SEED_ITEM.STATUS.eq("approved"))
                .fetchOptional(RELEASE_SEED_ITEM.QUESTION_ID);
    }

    @Override
    public void recordRelations(UUID batchId, UUID workerToken, int relationCount, Duration leaseDuration) {
        OffsetDateTime now = OffsetDateTime.now();
        int changed = database.update(RELEASE_SEED_BATCH)
                .set(RELEASE_SEED_BATCH.RELATION_COUNT, relationCount)
                .set(RELEASE_SEED_BATCH.LEASE_EXPIRES_AT, now.plus(leaseDuration))
                .set(RELEASE_SEED_BATCH.UPDATED_AT, now)
                .where(RELEASE_SEED_BATCH.RELEASE_SEED_BATCH_ID.eq(batchId))
                .and(RELEASE_SEED_BATCH.WORKER_TOKEN.eq(workerToken))
                .execute();
        if (changed != 1) throw new ReleaseSeedValidationException("release_seed_batch_lease_lost");
    }

    @Override
    public ReleaseSeedBatchLease complete(UUID batchId, UUID workerToken) {
        OffsetDateTime now = OffsetDateTime.now();
        int changed = database.update(RELEASE_SEED_BATCH)
                .set(RELEASE_SEED_BATCH.STATUS, "completed")
                .setNull(RELEASE_SEED_BATCH.WORKER_TOKEN)
                .setNull(RELEASE_SEED_BATCH.LEASE_EXPIRES_AT)
                .set(RELEASE_SEED_BATCH.COMPLETED_AT, now)
                .set(RELEASE_SEED_BATCH.UPDATED_AT, now)
                .where(RELEASE_SEED_BATCH.RELEASE_SEED_BATCH_ID.eq(batchId))
                .and(RELEASE_SEED_BATCH.WORKER_TOKEN.eq(workerToken))
                .and(RELEASE_SEED_BATCH.NEXT_QUESTION_INDEX.eq(RELEASE_SEED_BATCH.QUESTION_COUNT))
                .execute();
        if (changed != 1) throw new ReleaseSeedValidationException("release_seed_batch_not_completable");
        return findById(batchId);
    }

    @Override
    public void fail(UUID batchId, UUID workerToken, String code) {
        ObjectNode error = objectMapper.createObjectNode().put("code", code);
        database.update(RELEASE_SEED_BATCH)
                .set(RELEASE_SEED_BATCH.STATUS, "failed")
                .setNull(RELEASE_SEED_BATCH.WORKER_TOKEN)
                .setNull(RELEASE_SEED_BATCH.LEASE_EXPIRES_AT)
                .set(RELEASE_SEED_BATCH.LAST_ERROR_JSON, json(error))
                .set(RELEASE_SEED_BATCH.UPDATED_AT, OffsetDateTime.now())
                .where(RELEASE_SEED_BATCH.RELEASE_SEED_BATCH_ID.eq(batchId))
                .and(RELEASE_SEED_BATCH.WORKER_TOKEN.eq(workerToken))
                .execute();
    }

    @Override
    public ReleaseSeedBatchLease find(UUID workspaceId, String packageContentHash) {
        var record = database.selectFrom(RELEASE_SEED_BATCH)
                .where(RELEASE_SEED_BATCH.WORKSPACE_ID.eq(workspaceId))
                .and(RELEASE_SEED_BATCH.PACKAGE_CONTENT_HASH.eq(packageContentHash))
                .fetchOne();
        if (record == null) throw new ReleaseSeedValidationException("release_seed_batch_not_found");
        return map(record);
    }

    @Override
    public ReleaseSeedVerification verify(UUID batchId) {
        var counts = database.select(
                        DSL.count().as("items"),
                        DSL.count().filterWhere(RELEASE_SEED_ITEM.STATUS.eq("approved")).as("approved"),
                        DSL.countDistinct(RELEASE_SEED_ITEM.QUESTION_REVISION_ID).as("revisions"))
                .from(RELEASE_SEED_ITEM)
                .where(RELEASE_SEED_ITEM.RELEASE_SEED_BATCH_ID.eq(batchId))
                .fetchOne();
        int decisions = database.selectCount().from(REVIEW_DECISION)
                .join(RELEASE_SEED_ITEM).on(RELEASE_SEED_ITEM.REVIEW_CASE_ID.eq(REVIEW_DECISION.REVIEW_CASE_ID))
                .where(RELEASE_SEED_ITEM.RELEASE_SEED_BATCH_ID.eq(batchId)).fetchOne(0, int.class);
        int documents = database.fetchCount(RELEASE_SEED_SOURCE_DOCUMENT_MAP,
                RELEASE_SEED_SOURCE_DOCUMENT_MAP.RELEASE_SEED_BATCH_ID.eq(batchId));
        int regions = database.fetchCount(RELEASE_SEED_SOURCE_REGION_MAP,
                RELEASE_SEED_SOURCE_REGION_MAP.RELEASE_SEED_BATCH_ID.eq(batchId));
        var batch = database.select(RELEASE_SEED_BATCH.RELATION_COUNT).from(RELEASE_SEED_BATCH)
                .where(RELEASE_SEED_BATCH.RELEASE_SEED_BATCH_ID.eq(batchId)).fetchOne();
        int taxonomyLinks = database.selectCount().from(QUESTION_TAXONOMY_LINK)
                .join(RELEASE_SEED_ITEM)
                .on(RELEASE_SEED_ITEM.QUESTION_REVISION_ID.eq(QUESTION_TAXONOMY_LINK.QUESTION_REVISION_ID))
                .where(RELEASE_SEED_ITEM.RELEASE_SEED_BATCH_ID.eq(batchId)).fetchOne(0, int.class);
        return new ReleaseSeedVerification(
                counts.get("items", int.class), counts.get("approved", int.class),
                counts.get("revisions", int.class), decisions, documents, regions,
                batch == null ? 0 : batch.get(RELEASE_SEED_BATCH.RELATION_COUNT), taxonomyLinks);
    }

    private ReleaseSeedBatchLease findById(UUID batchId) {
        var record = database.selectFrom(RELEASE_SEED_BATCH)
                .where(RELEASE_SEED_BATCH.RELEASE_SEED_BATCH_ID.eq(batchId)).fetchOne();
        if (record == null) throw new ReleaseSeedValidationException("release_seed_batch_not_found");
        return map(record);
    }

    private ReleaseSeedBatchLease map(com.teachbase.jooq.tables.records.ReleaseSeedBatchRecord record) {
        return new ReleaseSeedBatchLease(
                record.getReleaseSeedBatchId(), record.getWorkerToken(), record.getStatus(),
                record.getNextQuestionIndex(), record.getAttemptNo(), record.getQuestionCount(),
                record.getImportedCount(), record.getReusedCount(), record.getApprovedCount());
    }

    private JSON json(JsonNode value) {
        try {
            return JSON.valueOf(objectMapper.writeValueAsString(value));
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("release_seed_checkpoint_json_failed", exception);
        }
    }
}
