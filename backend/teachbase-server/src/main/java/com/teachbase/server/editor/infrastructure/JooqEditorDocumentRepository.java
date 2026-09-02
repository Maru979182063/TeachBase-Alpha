package com.teachbase.server.editor.infrastructure;

import static com.teachbase.jooq.tables.EditorAutosaveMutation.EDITOR_AUTOSAVE_MUTATION;
import static com.teachbase.jooq.tables.EditorDocument.EDITOR_DOCUMENT;
import static com.teachbase.jooq.tables.EditorDraft.EDITOR_DRAFT;
import static com.teachbase.jooq.tables.EditorDraftCheckpoint.EDITOR_DRAFT_CHECKPOINT;
import static com.teachbase.jooq.tables.EditorPreviewConfirmation.EDITOR_PREVIEW_CONFIRMATION;
import static com.teachbase.jooq.tables.EditorQuestionReference.EDITOR_QUESTION_REFERENCE;
import static com.teachbase.jooq.tables.EditorRevision.EDITOR_REVISION;
import static com.teachbase.jooq.tables.EditorSnapshot.EDITOR_SNAPSHOT;
import static com.teachbase.jooq.tables.EditorVariant.EDITOR_VARIANT;
import static com.teachbase.jooq.tables.EditorWorkingDraft.EDITOR_WORKING_DRAFT;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.teachbase.server.editor.application.CreateEditorDocumentCommand;
import com.teachbase.server.editor.application.CreateEditorSnapshotCommand;
import com.teachbase.server.editor.application.EditorDocumentNotFoundException;
import com.teachbase.server.editor.application.EditorDocumentRepository;
import com.teachbase.server.editor.application.EditorDraft;
import com.teachbase.server.editor.application.EditorMutationConflictException;
import com.teachbase.server.editor.application.EditorRevisionConflictException;
import com.teachbase.server.editor.application.EditorSnapshot;
import com.teachbase.server.editor.application.EditorVariantContract;
import com.teachbase.server.editor.application.EditorWorkingDraftProperties;
import com.teachbase.server.editor.application.EditorWriterFencedException;
import com.teachbase.server.editor.application.UpdateEditorDraftCommand;
import com.teachbase.server.editor.application.ValidatedEditorContent;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.jooq.DSLContext;
import org.jooq.JSON;
import org.jooq.Record;
import org.springframework.stereotype.Repository;

/**
 * 中文维护说明：working draft 是唯一可变编辑态；revision、confirmation 和 snapshot 只在显式冻结事务中追加。
 * 数据库 writer_mode 与触发器共同隔离旧 writer，避免 rollout 期间出现两个真相源。
 *
 * 英文术语对照：jOOQ implementation of WP-01 draft, migration, revision-freeze, and snapshot contracts.
 */
@Repository
class JooqEditorDocumentRepository implements EditorDocumentRepository {

    private final DSLContext database;
    private final ObjectMapper objectMapper;
    private final EditorWorkingDraftProperties properties;

    JooqEditorDocumentRepository(
            DSLContext database,
            ObjectMapper objectMapper,
            EditorWorkingDraftProperties properties) {
        this.database = database;
        this.objectMapper = objectMapper;
        this.properties = properties;
    }

    @Override
    public EditorDraft create(CreateEditorDocumentCommand command, ValidatedEditorContent content) {
        UUID documentId = UUID.randomUUID();
        OffsetDateTime now = OffsetDateTime.now();
        database.insertInto(EDITOR_DOCUMENT)
                .set(EDITOR_DOCUMENT.EDITOR_DOCUMENT_ID, documentId)
                .set(EDITOR_DOCUMENT.WORKSPACE_ID, command.workspaceId())
                .set(EDITOR_DOCUMENT.DOCUMENT_KIND, command.documentKind().trim())
                .set(EDITOR_DOCUMENT.TITLE, command.title().trim())
                .set(EDITOR_DOCUMENT.STATUS, "draft")
                .set(EDITOR_DOCUMENT.CURRENT_REVISION_NO, 0L)
                .set(EDITOR_DOCUMENT.WRITER_MODE, "working_draft")
                .set(EDITOR_DOCUMENT.CREATED_BY, command.actorUserId())
                .set(EDITOR_DOCUMENT.UPDATED_BY, command.actorUserId())
                .set(EDITOR_DOCUMENT.CREATED_AT, now)
                .set(EDITOR_DOCUMENT.UPDATED_AT, now)
                .execute();
        insertVariant(documentId, command.workspaceId(), EditorVariantContract.BASIC, (short) 0, now);
        insertVariant(documentId, command.workspaceId(), EditorVariantContract.ADVANCED, (short) 1, now);
        insertVariant(documentId, command.workspaceId(), EditorVariantContract.COMMON, (short) 2, now);
        JsonNode envelope = contentEnvelope(content);
        database.insertInto(EDITOR_WORKING_DRAFT)
                .set(EDITOR_WORKING_DRAFT.EDITOR_DOCUMENT_ID, documentId)
                .set(EDITOR_WORKING_DRAFT.WORKSPACE_ID, command.workspaceId())
                .set(EDITOR_WORKING_DRAFT.DRAFT_VERSION, 1L)
                .set(EDITOR_WORKING_DRAFT.CONTENT_JSON, json(envelope))
                .set(EDITOR_WORKING_DRAFT.CONTENT_HASH, content.contentHash())
                .set(EDITOR_WORKING_DRAFT.UPDATED_BY, command.actorUserId())
                .set(EDITOR_WORKING_DRAFT.UPDATED_AT, now)
                .execute();
        return toDraft(
                documentId, command.workspaceId(), command.documentKind().trim(), command.title().trim(),
                null, 0L, 1L, envelope, content.contentHash(), false);
    }

    @Override
    public EditorDraft update(UpdateEditorDraftCommand command, ValidatedEditorContent content) {
        JsonNode envelope = contentEnvelope(content);
        Optional<EditorDraft> replay = findMutation(command, content.contentHash());
        if (replay.isPresent()) return replay.get();

        findOrMigrateDraft(command.editorDocumentId(), command.workspaceId(), properties.lazyMigrationEnabled())
                .orElseThrow(EditorDocumentNotFoundException::new);
        var document = lockDocument(command.editorDocumentId(), command.workspaceId());
        if (!"working_draft".equals(document.get(EDITOR_DOCUMENT.WRITER_MODE))) {
            throw new EditorWriterFencedException();
        }
        OffsetDateTime now = OffsetDateTime.now();
        long nextVersion = command.expectedDraftVersion() + 1;
        int updated = database.update(EDITOR_WORKING_DRAFT)
                .set(EDITOR_WORKING_DRAFT.DRAFT_VERSION, nextVersion)
                .set(EDITOR_WORKING_DRAFT.CONTENT_JSON, json(envelope))
                .set(EDITOR_WORKING_DRAFT.CONTENT_HASH, content.contentHash())
                .set(EDITOR_WORKING_DRAFT.UPDATED_BY, command.actorUserId())
                .set(EDITOR_WORKING_DRAFT.UPDATED_AT, now)
                .where(EDITOR_WORKING_DRAFT.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                .and(EDITOR_WORKING_DRAFT.WORKSPACE_ID.eq(command.workspaceId()))
                .and(EDITOR_WORKING_DRAFT.DRAFT_VERSION.eq(command.expectedDraftVersion()))
                .execute();
        if (updated == 0) {
            Optional<EditorDraft> committedReplay = findMutation(command, content.contentHash());
            if (committedReplay.isPresent()) return committedReplay.get();
            Long current = database.select(EDITOR_WORKING_DRAFT.DRAFT_VERSION)
                    .from(EDITOR_WORKING_DRAFT)
                    .where(EDITOR_WORKING_DRAFT.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                    .and(EDITOR_WORKING_DRAFT.WORKSPACE_ID.eq(command.workspaceId()))
                    .fetchOne(EDITOR_WORKING_DRAFT.DRAFT_VERSION);
            if (current == null) throw new EditorDocumentNotFoundException();
            throw new EditorRevisionConflictException(current);
        }

        UUID baseRevisionId = database.select(EDITOR_WORKING_DRAFT.BASE_REVISION_ID)
                .from(EDITOR_WORKING_DRAFT)
                .where(EDITOR_WORKING_DRAFT.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                .fetchOne(EDITOR_WORKING_DRAFT.BASE_REVISION_ID);
        database.insertInto(EDITOR_AUTOSAVE_MUTATION)
                .set(EDITOR_AUTOSAVE_MUTATION.EDITOR_AUTOSAVE_MUTATION_ID, UUID.randomUUID())
                .set(EDITOR_AUTOSAVE_MUTATION.EDITOR_DOCUMENT_ID, command.editorDocumentId())
                .set(EDITOR_AUTOSAVE_MUTATION.WORKSPACE_ID, command.workspaceId())
                .set(EDITOR_AUTOSAVE_MUTATION.CLIENT_MUTATION_ID, command.clientMutationId().trim())
                .set(EDITOR_AUTOSAVE_MUTATION.EXPECTED_DRAFT_VERSION, command.expectedDraftVersion())
                .set(EDITOR_AUTOSAVE_MUTATION.RESULTING_DRAFT_VERSION, nextVersion)
                .set(EDITOR_AUTOSAVE_MUTATION.BASE_REVISION_ID, baseRevisionId)
                .set(EDITOR_AUTOSAVE_MUTATION.CONTENT_JSON, json(envelope))
                .set(EDITOR_AUTOSAVE_MUTATION.CONTENT_HASH, content.contentHash())
                .set(EDITOR_AUTOSAVE_MUTATION.UPDATED_BY, command.actorUserId())
                .set(EDITOR_AUTOSAVE_MUTATION.UPDATED_AT, now)
                .set(EDITOR_AUTOSAVE_MUTATION.EXPIRES_AT, now.plus(properties.effectiveMutationTtl()))
                .execute();
        maybeCheckpoint(command, nextVersion, envelope, content.contentHash(), now);
        database.update(EDITOR_DOCUMENT)
                .set(EDITOR_DOCUMENT.UPDATED_BY, command.actorUserId())
                .set(EDITOR_DOCUMENT.UPDATED_AT, now)
                .where(EDITOR_DOCUMENT.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                .execute();
        return toDraft(
                command.editorDocumentId(), command.workspaceId(), document.get(EDITOR_DOCUMENT.DOCUMENT_KIND),
                document.get(EDITOR_DOCUMENT.TITLE), baseRevisionId,
                revisionNo(baseRevisionId), nextVersion, envelope, content.contentHash(), false);
    }

    @Override
    public Optional<EditorDraft> findOrMigrateDraft(
            UUID editorDocumentId,
            UUID workspaceId,
            boolean migrationAllowed) {
        Optional<EditorDraft> current = readWorkingDraft(editorDocumentId, workspaceId);
        if (current.isPresent()) return current;
        if (!migrationAllowed) throw new EditorWriterFencedException();

        var document = lockDocument(editorDocumentId, workspaceId);
        current = readWorkingDraft(editorDocumentId, workspaceId);
        if (current.isPresent()) return current;
        var legacy = database.select(
                        EDITOR_DRAFT.EDITOR_REVISION_ID,
                        EDITOR_DRAFT.REVISION_NO,
                        EDITOR_DRAFT.UPDATED_BY,
                        EDITOR_DRAFT.UPDATED_AT,
                        EDITOR_REVISION.SCHEMA_VERSION,
                        EDITOR_REVISION.MASTER_DOC_JSON,
                        EDITOR_REVISION.VERSION_OVERRIDES_JSON,
                        EDITOR_REVISION.CONTENT_HASH)
                .from(EDITOR_DRAFT)
                .join(EDITOR_REVISION).on(EDITOR_REVISION.EDITOR_REVISION_ID.eq(EDITOR_DRAFT.EDITOR_REVISION_ID))
                .where(EDITOR_DRAFT.EDITOR_DOCUMENT_ID.eq(editorDocumentId))
                .and(EDITOR_DRAFT.WORKSPACE_ID.eq(workspaceId))
                .fetchOne();
        if (legacy == null) throw new EditorDocumentNotFoundException();
        ObjectNode envelope = contentEnvelope(
                legacy.get(EDITOR_REVISION.SCHEMA_VERSION),
                parse(legacy.get(EDITOR_REVISION.MASTER_DOC_JSON)),
                parse(legacy.get(EDITOR_REVISION.VERSION_OVERRIDES_JSON)));
        Long existingVersion = database.select(EDITOR_WORKING_DRAFT.DRAFT_VERSION)
                .from(EDITOR_WORKING_DRAFT)
                .where(EDITOR_WORKING_DRAFT.EDITOR_DOCUMENT_ID.eq(editorDocumentId))
                .fetchOne(EDITOR_WORKING_DRAFT.DRAFT_VERSION);
        long migratedVersion = existingVersion == null ? 1L : existingVersion + 1;
        if (existingVersion == null) {
            database.insertInto(EDITOR_WORKING_DRAFT)
                    .set(EDITOR_WORKING_DRAFT.EDITOR_DOCUMENT_ID, editorDocumentId)
                    .set(EDITOR_WORKING_DRAFT.WORKSPACE_ID, workspaceId)
                    .set(EDITOR_WORKING_DRAFT.BASE_REVISION_ID, legacy.get(EDITOR_DRAFT.EDITOR_REVISION_ID))
                    .set(EDITOR_WORKING_DRAFT.DRAFT_VERSION, migratedVersion)
                    .set(EDITOR_WORKING_DRAFT.CONTENT_JSON, json(envelope))
                    .set(EDITOR_WORKING_DRAFT.CONTENT_HASH, legacy.get(EDITOR_REVISION.CONTENT_HASH))
                    .set(EDITOR_WORKING_DRAFT.UPDATED_BY, legacy.get(EDITOR_DRAFT.UPDATED_BY))
                    .set(EDITOR_WORKING_DRAFT.UPDATED_AT, legacy.get(EDITOR_DRAFT.UPDATED_AT))
                    .execute();
        } else {
            // 回滚后重新启用时，以 legacy writer 最后一次成功内容重新建立唯一可变真相。
            database.update(EDITOR_WORKING_DRAFT)
                    .set(EDITOR_WORKING_DRAFT.BASE_REVISION_ID, legacy.get(EDITOR_DRAFT.EDITOR_REVISION_ID))
                    .set(EDITOR_WORKING_DRAFT.DRAFT_VERSION, migratedVersion)
                    .set(EDITOR_WORKING_DRAFT.CONTENT_JSON, json(envelope))
                    .set(EDITOR_WORKING_DRAFT.CONTENT_HASH, legacy.get(EDITOR_REVISION.CONTENT_HASH))
                    .set(EDITOR_WORKING_DRAFT.UPDATED_BY, legacy.get(EDITOR_DRAFT.UPDATED_BY))
                    .set(EDITOR_WORKING_DRAFT.UPDATED_AT, legacy.get(EDITOR_DRAFT.UPDATED_AT))
                    .where(EDITOR_WORKING_DRAFT.EDITOR_DOCUMENT_ID.eq(editorDocumentId))
                    .execute();
        }
        database.update(EDITOR_DOCUMENT)
                .set(EDITOR_DOCUMENT.WRITER_MODE, "working_draft")
                .where(EDITOR_DOCUMENT.EDITOR_DOCUMENT_ID.eq(editorDocumentId))
                .and(EDITOR_DOCUMENT.WORKSPACE_ID.eq(workspaceId))
                .execute();
        return Optional.of(toDraft(
                editorDocumentId, workspaceId, document.get(EDITOR_DOCUMENT.DOCUMENT_KIND),
                document.get(EDITOR_DOCUMENT.TITLE), legacy.get(EDITOR_DRAFT.EDITOR_REVISION_ID),
                legacy.get(EDITOR_DRAFT.REVISION_NO), migratedVersion, envelope,
                legacy.get(EDITOR_REVISION.CONTENT_HASH), false));
    }

    @Override
    public EditorSnapshot createSnapshot(
            CreateEditorSnapshotCommand command,
            ValidatedEditorContent projectedContent) {
        var document = lockDocument(command.editorDocumentId(), command.workspaceId());
        if (!"working_draft".equals(document.get(EDITOR_DOCUMENT.WRITER_MODE))) {
            throw new EditorWriterFencedException();
        }
        var working = database.select(
                        EDITOR_WORKING_DRAFT.DRAFT_VERSION,
                        EDITOR_WORKING_DRAFT.CONTENT_JSON,
                        EDITOR_WORKING_DRAFT.CONTENT_HASH)
                .from(EDITOR_WORKING_DRAFT)
                .where(EDITOR_WORKING_DRAFT.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                .and(EDITOR_WORKING_DRAFT.WORKSPACE_ID.eq(command.workspaceId()))
                .forUpdate()
                .fetchOne();
        if (working == null) throw new EditorDocumentNotFoundException();
        long currentVersion = working.get(EDITOR_WORKING_DRAFT.DRAFT_VERSION);
        if (currentVersion != command.expectedDraftVersion()) {
            throw new EditorRevisionConflictException(currentVersion);
        }
        JsonNode envelope = parse(working.get(EDITOR_WORKING_DRAFT.CONTENT_JSON));
        String contentHash = working.get(EDITOR_WORKING_DRAFT.CONTENT_HASH);
        var reusable = database.select(EDITOR_REVISION.EDITOR_REVISION_ID, EDITOR_REVISION.REVISION_NO)
                .from(EDITOR_REVISION)
                .where(EDITOR_REVISION.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                .and(EDITOR_REVISION.WORKSPACE_ID.eq(command.workspaceId()))
                .and(EDITOR_REVISION.CONTENT_HASH.eq(contentHash))
                .orderBy(EDITOR_REVISION.REVISION_NO.desc())
                .limit(1)
                .fetchOne();
        UUID revisionId;
        long revisionNo;
        OffsetDateTime now = OffsetDateTime.now();
        if (reusable != null) {
            revisionId = reusable.get(EDITOR_REVISION.EDITOR_REVISION_ID);
            revisionNo = reusable.get(EDITOR_REVISION.REVISION_NO);
        } else {
            revisionId = UUID.randomUUID();
            revisionNo = document.get(EDITOR_DOCUMENT.CURRENT_REVISION_NO) + 1;
            insertRevision(
                    command.editorDocumentId(), command.workspaceId(), revisionId, revisionNo,
                    command.actorUserId(), envelope, contentHash, now);
            database.update(EDITOR_DOCUMENT)
                    .set(EDITOR_DOCUMENT.CURRENT_REVISION_NO, revisionNo)
                    .set(EDITOR_DOCUMENT.UPDATED_BY, command.actorUserId())
                    .set(EDITOR_DOCUMENT.UPDATED_AT, now)
                    .where(EDITOR_DOCUMENT.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                    .execute();
            indexQuestionReferences(
                    revisionId, command.editorDocumentId(), command.workspaceId(), command.actorUserId(),
                    envelope.path("masterDoc"));
        }
        database.update(EDITOR_WORKING_DRAFT)
                .set(EDITOR_WORKING_DRAFT.BASE_REVISION_ID, revisionId)
                .where(EDITOR_WORKING_DRAFT.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                .execute();

        UUID confirmationId = UUID.randomUUID();
        UUID snapshotId = UUID.randomUUID();
        database.insertInto(EDITOR_PREVIEW_CONFIRMATION)
                .set(EDITOR_PREVIEW_CONFIRMATION.EDITOR_PREVIEW_CONFIRMATION_ID, confirmationId)
                .set(EDITOR_PREVIEW_CONFIRMATION.EDITOR_DOCUMENT_ID, command.editorDocumentId())
                .set(EDITOR_PREVIEW_CONFIRMATION.WORKSPACE_ID, command.workspaceId())
                .set(EDITOR_PREVIEW_CONFIRMATION.EDITOR_REVISION_ID, revisionId)
                .set(EDITOR_PREVIEW_CONFIRMATION.VARIANT_KEY, command.variantKey())
                .set(EDITOR_PREVIEW_CONFIRMATION.AUDIENCE, command.audience())
                .set(EDITOR_PREVIEW_CONFIRMATION.CONFIRMED_BY, command.actorUserId())
                .set(EDITOR_PREVIEW_CONFIRMATION.CONFIRMED_AT, now)
                .execute();
        ObjectNode frozen = objectMapper.createObjectNode();
        frozen.put("editorModel", "master-overrides-v1");
        frozen.put("schemaVersion", command.schemaVersion());
        frozen.put("sourceRevisionNo", revisionNo);
        frozen.put("variantKey", command.variantKey());
        frozen.put("audience", command.audience());
        frozen.set("projectedDoc", projectedContent.masterDoc());
        database.insertInto(EDITOR_SNAPSHOT)
                .set(EDITOR_SNAPSHOT.EDITOR_SNAPSHOT_ID, snapshotId)
                .set(EDITOR_SNAPSHOT.EDITOR_DOCUMENT_ID, command.editorDocumentId())
                .set(EDITOR_SNAPSHOT.WORKSPACE_ID, command.workspaceId())
                .set(EDITOR_SNAPSHOT.EDITOR_REVISION_ID, revisionId)
                .set(EDITOR_SNAPSHOT.EDITOR_PREVIEW_CONFIRMATION_ID, confirmationId)
                .set(EDITOR_SNAPSHOT.VARIANT_KEY, command.variantKey())
                .set(EDITOR_SNAPSHOT.AUDIENCE, command.audience())
                .set(EDITOR_SNAPSHOT.SCHEMA_VERSION, command.schemaVersion())
                .set(EDITOR_SNAPSHOT.FROZEN_CONTENT_JSON, json(frozen))
                .set(EDITOR_SNAPSHOT.CONTENT_HASH, projectedContent.contentHash())
                .set(EDITOR_SNAPSHOT.CREATED_AT, now)
                .execute();
        return new EditorSnapshot(
                snapshotId, command.editorDocumentId(), revisionId, revisionNo, command.variantKey(),
                command.audience(), command.schemaVersion(), frozen, projectedContent.contentHash());
    }

    @Override
    public int cleanExpiredRecoveryState() {
        int mutations = database.deleteFrom(EDITOR_AUTOSAVE_MUTATION)
                .where(EDITOR_AUTOSAVE_MUTATION.EXPIRES_AT.lt(OffsetDateTime.now()))
                .execute();
        int checkpoints = database.execute(
                "delete from teachbase_app.editor_draft_checkpoint where editor_draft_checkpoint_id in ("
                        + "select editor_draft_checkpoint_id from ("
                        + "select editor_draft_checkpoint_id, expires_at, row_number() over ("
                        + "partition by editor_document_id order by created_at desc, editor_draft_checkpoint_id desc) as rn "
                        + "from teachbase_app.editor_draft_checkpoint) ranked "
                        + "where rn > ? or (rn > 1 and expires_at < now()))",
                properties.effectiveCheckpointMaxPerDocument());
        return mutations + checkpoints;
    }

    private Optional<EditorDraft> readWorkingDraft(UUID documentId, UUID workspaceId) {
        return database.select(
                        EDITOR_DOCUMENT.DOCUMENT_KIND,
                        EDITOR_DOCUMENT.TITLE,
                        EDITOR_WORKING_DRAFT.BASE_REVISION_ID,
                        EDITOR_WORKING_DRAFT.DRAFT_VERSION,
                        EDITOR_WORKING_DRAFT.CONTENT_JSON,
                        EDITOR_WORKING_DRAFT.CONTENT_HASH)
                .from(EDITOR_WORKING_DRAFT)
                .join(EDITOR_DOCUMENT).on(EDITOR_DOCUMENT.EDITOR_DOCUMENT_ID.eq(EDITOR_WORKING_DRAFT.EDITOR_DOCUMENT_ID))
                .where(EDITOR_WORKING_DRAFT.EDITOR_DOCUMENT_ID.eq(documentId))
                .and(EDITOR_WORKING_DRAFT.WORKSPACE_ID.eq(workspaceId))
                .and(EDITOR_DOCUMENT.WRITER_MODE.eq("working_draft"))
                .fetchOptional(record -> {
                    UUID base = record.get(EDITOR_WORKING_DRAFT.BASE_REVISION_ID);
                    return toDraft(
                            documentId, workspaceId, record.get(EDITOR_DOCUMENT.DOCUMENT_KIND),
                            record.get(EDITOR_DOCUMENT.TITLE), base, revisionNo(base),
                            record.get(EDITOR_WORKING_DRAFT.DRAFT_VERSION),
                            parse(record.get(EDITOR_WORKING_DRAFT.CONTENT_JSON)),
                            record.get(EDITOR_WORKING_DRAFT.CONTENT_HASH), false);
                });
    }

    private Optional<EditorDraft> findMutation(UpdateEditorDraftCommand command, String contentHash) {
        var mutation = database.select(
                        EDITOR_AUTOSAVE_MUTATION.EXPECTED_DRAFT_VERSION,
                        EDITOR_AUTOSAVE_MUTATION.RESULTING_DRAFT_VERSION,
                        EDITOR_AUTOSAVE_MUTATION.BASE_REVISION_ID,
                        EDITOR_AUTOSAVE_MUTATION.CONTENT_JSON,
                        EDITOR_AUTOSAVE_MUTATION.CONTENT_HASH)
                .from(EDITOR_AUTOSAVE_MUTATION)
                .where(EDITOR_AUTOSAVE_MUTATION.WORKSPACE_ID.eq(command.workspaceId()))
                .and(EDITOR_AUTOSAVE_MUTATION.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                .and(EDITOR_AUTOSAVE_MUTATION.CLIENT_MUTATION_ID.eq(command.clientMutationId().trim()))
                .fetchOne();
        if (mutation == null) return Optional.empty();
        if (mutation.get(EDITOR_AUTOSAVE_MUTATION.EXPECTED_DRAFT_VERSION) != command.expectedDraftVersion()
                || !mutation.get(EDITOR_AUTOSAVE_MUTATION.CONTENT_HASH).equals(contentHash)) {
            throw new EditorMutationConflictException();
        }
        var document = database.select(
                        EDITOR_DOCUMENT.DOCUMENT_KIND, EDITOR_DOCUMENT.TITLE, EDITOR_DOCUMENT.WRITER_MODE)
                .from(EDITOR_DOCUMENT)
                .where(EDITOR_DOCUMENT.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                .and(EDITOR_DOCUMENT.WORKSPACE_ID.eq(command.workspaceId()))
                .fetchOne();
        if (document == null) throw new EditorDocumentNotFoundException();
        if (!"working_draft".equals(document.get(EDITOR_DOCUMENT.WRITER_MODE))) {
            throw new EditorWriterFencedException();
        }
        UUID base = mutation.get(EDITOR_AUTOSAVE_MUTATION.BASE_REVISION_ID);
        return Optional.of(toDraft(
                command.editorDocumentId(), command.workspaceId(), document.get(EDITOR_DOCUMENT.DOCUMENT_KIND),
                document.get(EDITOR_DOCUMENT.TITLE), base, revisionNo(base),
                mutation.get(EDITOR_AUTOSAVE_MUTATION.RESULTING_DRAFT_VERSION),
                parse(mutation.get(EDITOR_AUTOSAVE_MUTATION.CONTENT_JSON)), contentHash, true));
    }

    private Record lockDocument(UUID documentId, UUID workspaceId) {
        var document = database.select(
                        EDITOR_DOCUMENT.DOCUMENT_KIND,
                        EDITOR_DOCUMENT.TITLE,
                        EDITOR_DOCUMENT.CURRENT_REVISION_NO,
                        EDITOR_DOCUMENT.WRITER_MODE)
                .from(EDITOR_DOCUMENT)
                .where(EDITOR_DOCUMENT.EDITOR_DOCUMENT_ID.eq(documentId))
                .and(EDITOR_DOCUMENT.WORKSPACE_ID.eq(workspaceId))
                .and(EDITOR_DOCUMENT.STATUS.ne("archived"))
                .forUpdate()
                .fetchOne();
        if (document == null) throw new EditorDocumentNotFoundException();
        return document;
    }

    private void maybeCheckpoint(
            UpdateEditorDraftCommand command,
            long draftVersion,
            JsonNode content,
            String contentHash,
            OffsetDateTime now) {
        OffsetDateTime threshold = now.minus(properties.effectiveCheckpointInterval());
        boolean recentExists = database.fetchExists(
                database.selectOne()
                        .from(EDITOR_DRAFT_CHECKPOINT)
                        .where(EDITOR_DRAFT_CHECKPOINT.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                        .and(EDITOR_DRAFT_CHECKPOINT.CHECKPOINT_KIND.eq("autosave"))
                        .and(EDITOR_DRAFT_CHECKPOINT.CREATED_AT.gt(threshold)));
        if (recentExists) return;
        database.insertInto(EDITOR_DRAFT_CHECKPOINT)
                .set(EDITOR_DRAFT_CHECKPOINT.EDITOR_DRAFT_CHECKPOINT_ID, UUID.randomUUID())
                .set(EDITOR_DRAFT_CHECKPOINT.EDITOR_DOCUMENT_ID, command.editorDocumentId())
                .set(EDITOR_DRAFT_CHECKPOINT.WORKSPACE_ID, command.workspaceId())
                .set(EDITOR_DRAFT_CHECKPOINT.DRAFT_VERSION, draftVersion)
                .set(EDITOR_DRAFT_CHECKPOINT.CHECKPOINT_KIND, "autosave")
                .set(EDITOR_DRAFT_CHECKPOINT.CONTENT_JSON, json(content))
                .set(EDITOR_DRAFT_CHECKPOINT.CONTENT_HASH, contentHash)
                .set(EDITOR_DRAFT_CHECKPOINT.CREATED_BY, command.actorUserId())
                .set(EDITOR_DRAFT_CHECKPOINT.CREATED_AT, now)
                .set(EDITOR_DRAFT_CHECKPOINT.EXPIRES_AT, now.plus(properties.effectiveCheckpointTtl()))
                .execute();
    }

    private void insertVariant(UUID documentId, UUID workspaceId, String key, short order, OffsetDateTime now) {
        database.insertInto(EDITOR_VARIANT)
                .set(EDITOR_VARIANT.EDITOR_DOCUMENT_ID, documentId)
                .set(EDITOR_VARIANT.WORKSPACE_ID, workspaceId)
                .set(EDITOR_VARIANT.VARIANT_KEY, key)
                .set(EDITOR_VARIANT.DISPLAY_NAME, EditorVariantContract.displayName(key))
                .set(EDITOR_VARIANT.SORT_ORDER, order)
                .set(EDITOR_VARIANT.CREATED_AT, now)
                .execute();
    }

    private void insertRevision(
            UUID documentId,
            UUID workspaceId,
            UUID revisionId,
            long revisionNo,
            UUID actorUserId,
            JsonNode envelope,
            String contentHash,
            OffsetDateTime now) {
        database.insertInto(EDITOR_REVISION)
                .set(EDITOR_REVISION.EDITOR_REVISION_ID, revisionId)
                .set(EDITOR_REVISION.EDITOR_DOCUMENT_ID, documentId)
                .set(EDITOR_REVISION.WORKSPACE_ID, workspaceId)
                .set(EDITOR_REVISION.REVISION_NO, revisionNo)
                .set(EDITOR_REVISION.EDITOR_MODEL, "master-overrides-v1")
                .set(EDITOR_REVISION.SCHEMA_VERSION, envelope.path("schemaVersion").asInt())
                .set(EDITOR_REVISION.MASTER_DOC_JSON, json(envelope.path("masterDoc")))
                .set(EDITOR_REVISION.VERSION_OVERRIDES_JSON, json(envelope.path("versionOverrides")))
                .set(EDITOR_REVISION.CONTENT_HASH, contentHash)
                .set(EDITOR_REVISION.CREATED_BY, actorUserId)
                .set(EDITOR_REVISION.CREATED_AT, now)
                .execute();
    }

    private void indexQuestionReferences(
            UUID editorRevisionId,
            UUID documentId,
            UUID workspaceId,
            UUID actorUserId,
            JsonNode root) {
        List<JsonNode> references = new ArrayList<>();
        collectQuestionReferences(root, references);
        OffsetDateTime now = OffsetDateTime.now();
        int position = 0;
        for (JsonNode node : references) {
            JsonNode attrs = node.path("attrs");
            try {
                UUID questionId = UUID.fromString(attrs.path("questionId").asText());
                UUID questionRevisionId = UUID.fromString(attrs.path("questionRevisionId").asText());
                ArrayNode layers = objectMapper.createArrayNode();
                for (String layer : attrs.path("targetLayers").asText().split(",")) {
                    if (!layer.isBlank()) layers.add(layer.trim());
                }
                database.insertInto(EDITOR_QUESTION_REFERENCE)
                        .set(EDITOR_QUESTION_REFERENCE.EDITOR_QUESTION_REFERENCE_ID, UUID.randomUUID())
                        .set(EDITOR_QUESTION_REFERENCE.EDITOR_DOCUMENT_ID, documentId)
                        .set(EDITOR_QUESTION_REFERENCE.EDITOR_REVISION_ID, editorRevisionId)
                        .set(EDITOR_QUESTION_REFERENCE.WORKSPACE_ID, workspaceId)
                        .set(EDITOR_QUESTION_REFERENCE.QUESTION_ID, questionId)
                        .set(EDITOR_QUESTION_REFERENCE.QUESTION_REVISION_ID, questionRevisionId)
                        .set(EDITOR_QUESTION_REFERENCE.PLACEMENT_KEY, UUID.randomUUID())
                        .set(EDITOR_QUESTION_REFERENCE.POSITION_INDEX, position++)
                        .set(EDITOR_QUESTION_REFERENCE.TARGET_LAYERS_JSON, json(layers))
                        .set(EDITOR_QUESTION_REFERENCE.CREATED_BY, actorUserId)
                        .set(EDITOR_QUESTION_REFERENCE.CREATED_AT, now)
                        .execute();
            } catch (IllegalArgumentException ignored) {
                // 兼容历史演示节点：没有真实 UUID 的占位引用不会进入正式 usage index。
            }
        }
    }

    private void collectQuestionReferences(JsonNode node, List<JsonNode> result) {
        if (node == null) return;
        if (node.isObject() && "questionReference".equals(node.path("type").asText())) result.add(node);
        node.elements().forEachRemaining(child -> collectQuestionReferences(child, result));
    }

    private ObjectNode contentEnvelope(ValidatedEditorContent content) {
        return contentEnvelope(content.schemaVersion(), content.masterDoc(), content.versionOverrides());
    }

    private ObjectNode contentEnvelope(int schemaVersion, JsonNode masterDoc, JsonNode overrides) {
        ObjectNode envelope = objectMapper.createObjectNode();
        envelope.put("editorModel", "master-overrides-v1");
        envelope.put("schemaVersion", schemaVersion);
        envelope.set("masterDoc", masterDoc);
        envelope.set("versionOverrides", overrides);
        return envelope;
    }

    private EditorDraft toDraft(
            UUID documentId,
            UUID workspaceId,
            String kind,
            String title,
            UUID baseRevisionId,
            long baseRevisionNo,
            long draftVersion,
            JsonNode envelope,
            String contentHash,
            boolean replay) {
        return new EditorDraft(
                documentId, workspaceId, kind, title, baseRevisionId, baseRevisionNo, draftVersion,
                envelope.path("schemaVersion").asInt(), envelope.path("masterDoc"),
                envelope.path("versionOverrides"), contentHash, replay);
    }

    private long revisionNo(UUID revisionId) {
        if (revisionId == null) return 0L;
        Long value = database.select(EDITOR_REVISION.REVISION_NO)
                .from(EDITOR_REVISION)
                .where(EDITOR_REVISION.EDITOR_REVISION_ID.eq(revisionId))
                .fetchOne(EDITOR_REVISION.REVISION_NO);
        return value == null ? 0L : value;
    }

    private JSON json(JsonNode value) {
        try {
            return JSON.valueOf(objectMapper.writeValueAsString(value));
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("editor_json_not_serializable", exception);
        }
    }

    private JsonNode parse(JSON json) {
        try {
            return objectMapper.readTree(json.data());
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("stored_editor_json_invalid", exception);
        }
    }
}
