package com.teachbase.server.collection.infrastructure;

import static com.teachbase.jooq.tables.QuestionCollection.QUESTION_COLLECTION;
import static com.teachbase.jooq.tables.QuestionCollectionCheckpoint.QUESTION_COLLECTION_CHECKPOINT;
import static com.teachbase.jooq.tables.QuestionCollectionItem.QUESTION_COLLECTION_ITEM;
import static com.teachbase.jooq.tables.QuestionCollectionSnapshot.QUESTION_COLLECTION_SNAPSHOT;
import static com.teachbase.jooq.tables.QuestionCollectionSnapshotItem.QUESTION_COLLECTION_SNAPSHOT_ITEM;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.teachbase.server.collection.api.CollectionItemResponse;
import com.teachbase.server.collection.application.CollectionDraft;
import com.teachbase.server.collection.application.CollectionCheckpoint;
import com.teachbase.server.collection.application.CollectionNotFoundException;
import com.teachbase.server.collection.application.CollectionRepository;
import com.teachbase.server.collection.application.CollectionSnapshot;
import com.teachbase.server.collection.application.CollectionVersionConflictException;
import com.teachbase.server.question.api.QuestionRevisionDescriptor;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.jooq.DSLContext;
import org.jooq.JSON;
import org.springframework.stereotype.Repository;

/**
 * 中文维护说明：本文件属于题篮与快照模块的数据库或外部工具适配层，负责落实持久化合同；并发正确性最终由事务、锁和数据库约束共同保证。
 *
 * 英文术语对照：jOOQ persistence for atomic basket replacement, checkpoints, and frozen snapshots.
 */
@Repository
class JooqCollectionRepository implements CollectionRepository {

    private final DSLContext database;
    private final ObjectMapper objectMapper;

    JooqCollectionRepository(DSLContext database, ObjectMapper objectMapper) {
        this.database = database;
        this.objectMapper = objectMapper;
    }

    @Override
    public CollectionDraft create(UUID workspaceId, UUID actorUserId, String name) {
        UUID id = UUID.randomUUID();
        OffsetDateTime now = OffsetDateTime.now();
        database.insertInto(QUESTION_COLLECTION)
                .set(QUESTION_COLLECTION.QUESTION_COLLECTION_ID, id)
                .set(QUESTION_COLLECTION.WORKSPACE_ID, workspaceId)
                .set(QUESTION_COLLECTION.NAME, name)
                .set(QUESTION_COLLECTION.STATUS, "draft")
                .set(QUESTION_COLLECTION.DRAFT_VERSION, 0L)
                .set(QUESTION_COLLECTION.CREATED_BY, actorUserId)
                .set(QUESTION_COLLECTION.UPDATED_BY, actorUserId)
                .set(QUESTION_COLLECTION.CREATED_AT, now)
                .set(QUESTION_COLLECTION.UPDATED_AT, now)
                .execute();
        return new CollectionDraft(id, workspaceId, name, "draft", 0L, List.of());
    }

    @Override
    public Optional<CollectionDraft> find(UUID collectionId, UUID workspaceId) {
        var collection = database.select(
                        QUESTION_COLLECTION.NAME,
                        QUESTION_COLLECTION.STATUS,
                        QUESTION_COLLECTION.DRAFT_VERSION)
                .from(QUESTION_COLLECTION)
                .where(QUESTION_COLLECTION.QUESTION_COLLECTION_ID.eq(collectionId))
                .and(QUESTION_COLLECTION.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_COLLECTION.STATUS.ne("archived"))
                .fetchOne();
        if (collection == null) return Optional.empty();
        return Optional.of(new CollectionDraft(
                collectionId,
                workspaceId,
                collection.get(QUESTION_COLLECTION.NAME),
                collection.get(QUESTION_COLLECTION.STATUS),
                collection.get(QUESTION_COLLECTION.DRAFT_VERSION),
                loadItems(collectionId, workspaceId)));
    }

    @Override
    public List<CollectionCheckpoint> listCheckpoints(UUID collectionId, UUID workspaceId, int limit) {
        OffsetDateTime now = OffsetDateTime.now();
        return database.selectFrom(QUESTION_COLLECTION_CHECKPOINT)
                .where(QUESTION_COLLECTION_CHECKPOINT.QUESTION_COLLECTION_ID.eq(collectionId))
                .and(QUESTION_COLLECTION_CHECKPOINT.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_COLLECTION_CHECKPOINT.EXPIRES_AT.isNull()
                        .or(QUESTION_COLLECTION_CHECKPOINT.EXPIRES_AT.gt(now)))
                .orderBy(QUESTION_COLLECTION_CHECKPOINT.DRAFT_VERSION.desc())
                .limit(limit)
                .fetch(record -> checkpoint(record));
    }

    @Override
    public Optional<CollectionCheckpoint> findCheckpoint(
            UUID collectionId, UUID checkpointId, UUID workspaceId) {
        OffsetDateTime now = OffsetDateTime.now();
        return database.selectFrom(QUESTION_COLLECTION_CHECKPOINT)
                .where(QUESTION_COLLECTION_CHECKPOINT.QUESTION_COLLECTION_CHECKPOINT_ID.eq(checkpointId))
                .and(QUESTION_COLLECTION_CHECKPOINT.QUESTION_COLLECTION_ID.eq(collectionId))
                .and(QUESTION_COLLECTION_CHECKPOINT.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_COLLECTION_CHECKPOINT.EXPIRES_AT.isNull()
                        .or(QUESTION_COLLECTION_CHECKPOINT.EXPIRES_AT.gt(now)))
                .fetchOptional(this::checkpoint);
    }

    @Override
    public CollectionDraft save(
            UUID collectionId,
            UUID workspaceId,
            UUID actorUserId,
            long expectedVersion,
            String checkpointKind,
            List<QuestionRevisionDescriptor> revisions,
            List<JsonNode> settings) {
        var collection = lock(collectionId, workspaceId);
        long currentVersion = collection.get(QUESTION_COLLECTION.DRAFT_VERSION);
        if (currentVersion != expectedVersion) throw new CollectionVersionConflictException(currentVersion);
        long nextVersion = currentVersion + 1;
        OffsetDateTime now = OffsetDateTime.now();

        // 删除和重新插入都在同一事务持有聚合根锁期间完成，
        // 因此读取方只能看到完整的旧顺序或完整的新顺序，不会看到半成品。
        database.deleteFrom(QUESTION_COLLECTION_ITEM)
                .where(QUESTION_COLLECTION_ITEM.QUESTION_COLLECTION_ID.eq(collectionId))
                .execute();
        for (int index = 0; index < revisions.size(); index++) {
            QuestionRevisionDescriptor revision = revisions.get(index);
            database.insertInto(QUESTION_COLLECTION_ITEM)
                    .set(QUESTION_COLLECTION_ITEM.QUESTION_COLLECTION_ID, collectionId)
                    .set(QUESTION_COLLECTION_ITEM.WORKSPACE_ID, workspaceId)
                    .set(QUESTION_COLLECTION_ITEM.QUESTION_ID, revision.questionId())
                    .set(QUESTION_COLLECTION_ITEM.QUESTION_REVISION_ID, revision.questionRevisionId())
                    .set(QUESTION_COLLECTION_ITEM.POSITION_INDEX, index)
                    .set(QUESTION_COLLECTION_ITEM.SETTINGS_JSON, json(settings.get(index)))
                    .set(QUESTION_COLLECTION_ITEM.ADDED_BY, actorUserId)
                    .set(QUESTION_COLLECTION_ITEM.ADDED_AT, now)
                    .execute();
        }
        database.update(QUESTION_COLLECTION)
                .set(QUESTION_COLLECTION.DRAFT_VERSION, nextVersion)
                .set(QUESTION_COLLECTION.UPDATED_BY, actorUserId)
                .set(QUESTION_COLLECTION.UPDATED_AT, now)
                .where(QUESTION_COLLECTION.QUESTION_COLLECTION_ID.eq(collectionId))
                .execute();

        ObjectNode checkpoint = collectionEnvelope(
                collectionId, collection.get(QUESTION_COLLECTION.NAME), nextVersion, revisions, settings);
        database.insertInto(QUESTION_COLLECTION_CHECKPOINT)
                .set(QUESTION_COLLECTION_CHECKPOINT.QUESTION_COLLECTION_CHECKPOINT_ID, UUID.randomUUID())
                .set(QUESTION_COLLECTION_CHECKPOINT.QUESTION_COLLECTION_ID, collectionId)
                .set(QUESTION_COLLECTION_CHECKPOINT.WORKSPACE_ID, workspaceId)
                .set(QUESTION_COLLECTION_CHECKPOINT.DRAFT_VERSION, nextVersion)
                .set(QUESTION_COLLECTION_CHECKPOINT.CONTENT_JSON, json(checkpoint))
                .set(QUESTION_COLLECTION_CHECKPOINT.CONTENT_HASH, sha256(checkpoint))
                .set(QUESTION_COLLECTION_CHECKPOINT.CHECKPOINT_KIND, checkpointKind)
                .set(QUESTION_COLLECTION_CHECKPOINT.CREATED_BY, actorUserId)
                .set(QUESTION_COLLECTION_CHECKPOINT.CREATED_AT, now)
                .set(QUESTION_COLLECTION_CHECKPOINT.EXPIRES_AT,
                        checkpointKind.equals("autosave") ? now.plusDays(7) : null)
                .execute();
        return new CollectionDraft(
                collectionId, workspaceId, collection.get(QUESTION_COLLECTION.NAME),
                collection.get(QUESTION_COLLECTION.STATUS), nextVersion, loadItems(collectionId, workspaceId));
    }

    @Override
    public CollectionSnapshot snapshot(
            UUID collectionId,
            UUID workspaceId,
            UUID actorUserId,
            long expectedVersion,
            List<QuestionRevisionDescriptor> expectedRevisions) {
        var collection = lock(collectionId, workspaceId);
        long currentVersion = collection.get(QUESTION_COLLECTION.DRAFT_VERSION);
        if (currentVersion != expectedVersion) throw new CollectionVersionConflictException(currentVersion);
        List<CollectionItemResponse> items = loadItems(collectionId, workspaceId);
        List<UUID> currentIds = items.stream().map(CollectionItemResponse::questionRevisionId).toList();
        List<UUID> expectedIds = expectedRevisions.stream().map(QuestionRevisionDescriptor::questionRevisionId).toList();
        if (!currentIds.equals(expectedIds)) throw new CollectionVersionConflictException(currentVersion);

        List<JsonNode> settings = items.stream().map(CollectionItemResponse::settings).toList();
        ObjectNode frozen = collectionEnvelope(
                collectionId, collection.get(QUESTION_COLLECTION.NAME), currentVersion, expectedRevisions, settings);
        frozen.put("schemaVersion", 1);
        UUID snapshotId = UUID.randomUUID();
        String contentHash = sha256(frozen);
        OffsetDateTime now = OffsetDateTime.now();
        database.insertInto(QUESTION_COLLECTION_SNAPSHOT)
                .set(QUESTION_COLLECTION_SNAPSHOT.QUESTION_COLLECTION_SNAPSHOT_ID, snapshotId)
                .set(QUESTION_COLLECTION_SNAPSHOT.QUESTION_COLLECTION_ID, collectionId)
                .set(QUESTION_COLLECTION_SNAPSHOT.WORKSPACE_ID, workspaceId)
                .set(QUESTION_COLLECTION_SNAPSHOT.SOURCE_DRAFT_VERSION, currentVersion)
                .set(QUESTION_COLLECTION_SNAPSHOT.SCHEMA_VERSION, 1)
                .set(QUESTION_COLLECTION_SNAPSHOT.FROZEN_CONTENT_JSON, json(frozen))
                .set(QUESTION_COLLECTION_SNAPSHOT.CONTENT_HASH, contentHash)
                .set(QUESTION_COLLECTION_SNAPSHOT.CREATED_BY, actorUserId)
                .set(QUESTION_COLLECTION_SNAPSHOT.CREATED_AT, now)
                .execute();
        for (int index = 0; index < expectedRevisions.size(); index++) {
            QuestionRevisionDescriptor revision = expectedRevisions.get(index);
            database.insertInto(QUESTION_COLLECTION_SNAPSHOT_ITEM)
                    .set(QUESTION_COLLECTION_SNAPSHOT_ITEM.QUESTION_COLLECTION_SNAPSHOT_ID, snapshotId)
                    .set(QUESTION_COLLECTION_SNAPSHOT_ITEM.WORKSPACE_ID, workspaceId)
                    .set(QUESTION_COLLECTION_SNAPSHOT_ITEM.QUESTION_ID, revision.questionId())
                    .set(QUESTION_COLLECTION_SNAPSHOT_ITEM.QUESTION_REVISION_ID, revision.questionRevisionId())
                    .set(QUESTION_COLLECTION_SNAPSHOT_ITEM.POSITION_INDEX, index)
                    .set(QUESTION_COLLECTION_SNAPSHOT_ITEM.FROZEN_QUESTION_JSON, json(questionJson(revision)))
                    .execute();
        }
        return new CollectionSnapshot(snapshotId, collectionId, currentVersion, contentHash, frozen);
    }

    private org.jooq.Record3<String, String, Long> lock(UUID collectionId, UUID workspaceId) {
        var record = database.select(
                        QUESTION_COLLECTION.NAME,
                        QUESTION_COLLECTION.STATUS,
                        QUESTION_COLLECTION.DRAFT_VERSION)
                .from(QUESTION_COLLECTION)
                .where(QUESTION_COLLECTION.QUESTION_COLLECTION_ID.eq(collectionId))
                .and(QUESTION_COLLECTION.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_COLLECTION.STATUS.ne("archived"))
                .forUpdate()
                .fetchOne();
        if (record == null) throw new CollectionNotFoundException();
        return record;
    }

    private List<CollectionItemResponse> loadItems(UUID collectionId, UUID workspaceId) {
        return database.selectFrom(QUESTION_COLLECTION_ITEM)
                .where(QUESTION_COLLECTION_ITEM.QUESTION_COLLECTION_ID.eq(collectionId))
                .and(QUESTION_COLLECTION_ITEM.WORKSPACE_ID.eq(workspaceId))
                .orderBy(QUESTION_COLLECTION_ITEM.POSITION_INDEX.asc())
                .fetch(record -> new CollectionItemResponse(
                        record.getQuestionId(), record.getQuestionRevisionId(), record.getPositionIndex(),
                        parse(record.getSettingsJson())));
    }

    private CollectionCheckpoint checkpoint(
            com.teachbase.jooq.tables.records.QuestionCollectionCheckpointRecord record) {
        return new CollectionCheckpoint(
                record.getQuestionCollectionCheckpointId(), record.getDraftVersion(), record.getCheckpointKind(),
                record.getContentHash(), parse(record.getContentJson()), record.getCreatedAt(), record.getExpiresAt());
    }

    private ObjectNode collectionEnvelope(
            UUID collectionId,
            String name,
            long version,
            List<QuestionRevisionDescriptor> revisions,
            List<JsonNode> settings) {
        ObjectNode envelope = objectMapper.createObjectNode();
        envelope.put("questionCollectionId", collectionId.toString());
        envelope.put("name", name);
        envelope.put("draftVersion", version);
        ArrayNode items = envelope.putArray("items");
        for (int index = 0; index < revisions.size(); index++) {
            ObjectNode item = items.addObject();
            item.put("positionIndex", index);
            item.set("question", questionJson(revisions.get(index)));
            item.set("settings", settings.get(index));
        }
        return envelope;
    }

    private ObjectNode questionJson(QuestionRevisionDescriptor revision) {
        ObjectNode question = objectMapper.createObjectNode();
        question.put("questionId", revision.questionId().toString());
        question.put("questionRevisionId", revision.questionRevisionId().toString());
        question.put("revisionNo", revision.revisionNo());
        question.put("reviewStatus", revision.reviewStatus());
        question.put("subject", revision.subject());
        question.put("stage", revision.stage());
        question.put("grade", revision.grade());
        question.put("questionType", revision.questionType());
        question.put("title", revision.title());
        question.put("materialMarkdown", revision.materialMarkdown());
        question.put("stemMarkdown", revision.stemMarkdown());
        question.set("options", revision.options());
        question.put("answerMarkdown", revision.answerMarkdown());
        question.put("analysisMarkdown", revision.analysisMarkdown());
        question.set("content", revision.content());
        question.set("provenance", revision.provenance());
        question.put("contentHash", revision.contentHash());
        return question;
    }

    private String sha256(JsonNode value) {
        try {
            byte[] bytes = objectMapper.writeValueAsBytes(value);
            return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("collection_json_not_serializable", exception);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("sha256_unavailable", exception);
        }
    }

    private JSON json(JsonNode value) {
        try {
            return JSON.valueOf(objectMapper.writeValueAsString(value));
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("collection_json_not_serializable", exception);
        }
    }

    private JsonNode parse(JSON value) {
        try {
            return objectMapper.readTree(value.data());
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("stored_collection_json_invalid", exception);
        }
    }
}
