package com.teachbase.server.editor.infrastructure;

import static com.teachbase.jooq.tables.EditorDocument.EDITOR_DOCUMENT;
import static com.teachbase.jooq.tables.EditorDraft.EDITOR_DRAFT;
import static com.teachbase.jooq.tables.EditorRevision.EDITOR_REVISION;
import static com.teachbase.jooq.tables.EditorVariant.EDITOR_VARIANT;
import static com.teachbase.jooq.tables.EditorPreviewConfirmation.EDITOR_PREVIEW_CONFIRMATION;
import static com.teachbase.jooq.tables.EditorSnapshot.EDITOR_SNAPSHOT;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.editor.application.CreateEditorDocumentCommand;
import com.teachbase.server.editor.application.CreateEditorSnapshotCommand;
import com.teachbase.server.editor.application.EditorDocumentNotFoundException;
import com.teachbase.server.editor.application.EditorDocumentRepository;
import com.teachbase.server.editor.application.EditorDraft;
import com.teachbase.server.editor.application.EditorRevisionConflictException;
import com.teachbase.server.editor.application.EditorSnapshot;
import com.teachbase.server.editor.application.UpdateEditorDraftCommand;
import com.teachbase.server.editor.application.ValidatedEditorContent;
import java.time.OffsetDateTime;
import java.util.Optional;
import java.util.UUID;
import org.jooq.DSLContext;
import org.jooq.JSON;
import org.springframework.stereotype.Repository;

@Repository
/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，负责落实持久化合同；并发正确性最终由事务、锁和数据库约束共同保证。
 *
 * 英文术语对照：jOOQ implementation of the editor revision and snapshot persistence contract.
 */
class JooqEditorDocumentRepository implements EditorDocumentRepository {

    private final DSLContext database;
    private final ObjectMapper objectMapper;

    JooqEditorDocumentRepository(DSLContext database, ObjectMapper objectMapper) {
        this.database = database;
        this.objectMapper = objectMapper;
    }

    @Override
    public EditorDraft create(CreateEditorDocumentCommand command, ValidatedEditorContent content) {
        UUID documentId = UUID.randomUUID();
        UUID revisionId = UUID.randomUUID();
        OffsetDateTime now = OffsetDateTime.now();
        database.insertInto(EDITOR_DOCUMENT)
                .set(EDITOR_DOCUMENT.EDITOR_DOCUMENT_ID, documentId)
                .set(EDITOR_DOCUMENT.WORKSPACE_ID, command.workspaceId())
                .set(EDITOR_DOCUMENT.DOCUMENT_KIND, command.documentKind().trim())
                .set(EDITOR_DOCUMENT.TITLE, command.title().trim())
                .set(EDITOR_DOCUMENT.STATUS, "draft")
                .set(EDITOR_DOCUMENT.CURRENT_REVISION_NO, 1L)
                .set(EDITOR_DOCUMENT.CREATED_BY, command.actorUserId())
                .set(EDITOR_DOCUMENT.UPDATED_BY, command.actorUserId())
                .set(EDITOR_DOCUMENT.CREATED_AT, now)
                .set(EDITOR_DOCUMENT.UPDATED_AT, now)
                .execute();
        insertVariant(documentId, command.workspaceId(), "basic", "基础版", (short) 0, now);
        insertVariant(documentId, command.workspaceId(), "advanced", "进阶版", (short) 1, now);
        insertVariant(documentId, command.workspaceId(), "common", "常用版", (short) 2, now);
        insertRevision(documentId, command.workspaceId(), revisionId, 1L, command.actorUserId(), content, now);
        database.insertInto(EDITOR_DRAFT)
                .set(EDITOR_DRAFT.EDITOR_DOCUMENT_ID, documentId)
                .set(EDITOR_DRAFT.WORKSPACE_ID, command.workspaceId())
                .set(EDITOR_DRAFT.EDITOR_REVISION_ID, revisionId)
                .set(EDITOR_DRAFT.REVISION_NO, 1L)
                .set(EDITOR_DRAFT.UPDATED_BY, command.actorUserId())
                .set(EDITOR_DRAFT.UPDATED_AT, now)
                .execute();
        return toDraft(documentId, command.workspaceId(), command.documentKind().trim(), command.title().trim(), revisionId, 1L, content);
    }

    @Override
    public EditorDraft update(UpdateEditorDraftCommand command, ValidatedEditorContent content) {
        // 在聚合根上串行化相互竞争的保存操作；预期修订号检查把覆盖写入
        // 转换成明确的 HTTP 409，而不是静默丢失用户数据。
        var document = database.select(
                        EDITOR_DOCUMENT.DOCUMENT_KIND,
                        EDITOR_DOCUMENT.TITLE,
                        EDITOR_DOCUMENT.CURRENT_REVISION_NO)
                .from(EDITOR_DOCUMENT)
                .where(EDITOR_DOCUMENT.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                .and(EDITOR_DOCUMENT.WORKSPACE_ID.eq(command.workspaceId()))
                .and(EDITOR_DOCUMENT.STATUS.ne("archived"))
                .forUpdate()
                .fetchOne();
        if (document == null) throw new EditorDocumentNotFoundException();
        long currentRevision = document.get(EDITOR_DOCUMENT.CURRENT_REVISION_NO);
        if (currentRevision != command.expectedRevisionNo()) {
            throw new EditorRevisionConflictException(currentRevision);
        }
        long nextRevision = currentRevision + 1;
        UUID revisionId = UUID.randomUUID();
        OffsetDateTime now = OffsetDateTime.now();
        insertRevision(command.editorDocumentId(), command.workspaceId(), revisionId, nextRevision, command.actorUserId(), content, now);
        database.update(EDITOR_DOCUMENT)
                .set(EDITOR_DOCUMENT.CURRENT_REVISION_NO, nextRevision)
                .set(EDITOR_DOCUMENT.UPDATED_BY, command.actorUserId())
                .set(EDITOR_DOCUMENT.UPDATED_AT, now)
                .where(EDITOR_DOCUMENT.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                .execute();
        database.update(EDITOR_DRAFT)
                .set(EDITOR_DRAFT.EDITOR_REVISION_ID, revisionId)
                .set(EDITOR_DRAFT.REVISION_NO, nextRevision)
                .set(EDITOR_DRAFT.UPDATED_BY, command.actorUserId())
                .set(EDITOR_DRAFT.UPDATED_AT, now)
                .where(EDITOR_DRAFT.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                .execute();
        return toDraft(
                command.editorDocumentId(), command.workspaceId(), document.get(EDITOR_DOCUMENT.DOCUMENT_KIND),
                document.get(EDITOR_DOCUMENT.TITLE), revisionId, nextRevision, content);
    }

    @Override
    public Optional<EditorDraft> findDraft(UUID editorDocumentId, UUID workspaceId) {
        return database.select(
                        EDITOR_DOCUMENT.DOCUMENT_KIND,
                        EDITOR_DOCUMENT.TITLE,
                        EDITOR_DRAFT.EDITOR_REVISION_ID,
                        EDITOR_DRAFT.REVISION_NO,
                        EDITOR_REVISION.SCHEMA_VERSION,
                        EDITOR_REVISION.MASTER_DOC_JSON,
                        EDITOR_REVISION.VERSION_OVERRIDES_JSON,
                        EDITOR_REVISION.CONTENT_HASH)
                .from(EDITOR_DRAFT)
                .join(EDITOR_DOCUMENT).on(EDITOR_DOCUMENT.EDITOR_DOCUMENT_ID.eq(EDITOR_DRAFT.EDITOR_DOCUMENT_ID))
                .join(EDITOR_REVISION).on(EDITOR_REVISION.EDITOR_REVISION_ID.eq(EDITOR_DRAFT.EDITOR_REVISION_ID))
                .where(EDITOR_DRAFT.EDITOR_DOCUMENT_ID.eq(editorDocumentId))
                .and(EDITOR_DRAFT.WORKSPACE_ID.eq(workspaceId))
                .fetchOptional(record -> new EditorDraft(
                        editorDocumentId,
                        workspaceId,
                        record.get(EDITOR_DOCUMENT.DOCUMENT_KIND),
                        record.get(EDITOR_DOCUMENT.TITLE),
                        record.get(EDITOR_DRAFT.EDITOR_REVISION_ID),
                        record.get(EDITOR_DRAFT.REVISION_NO),
                        record.get(EDITOR_REVISION.SCHEMA_VERSION),
                        parse(record.get(EDITOR_REVISION.MASTER_DOC_JSON)),
                        parse(record.get(EDITOR_REVISION.VERSION_OVERRIDES_JSON)),
                        record.get(EDITOR_REVISION.CONTENT_HASH)));
    }

    @Override
    public EditorSnapshot createSnapshot(CreateEditorSnapshotCommand command, ValidatedEditorContent projectedContent) {
        // 在快照事务内部重新加锁，因为草稿可能在调用方读取后、
        // 到达本持久化方法前已经发生变化。
        var current = database.select(EDITOR_DOCUMENT.CURRENT_REVISION_NO)
                .from(EDITOR_DOCUMENT)
                .where(EDITOR_DOCUMENT.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                .and(EDITOR_DOCUMENT.WORKSPACE_ID.eq(command.workspaceId()))
                .and(EDITOR_DOCUMENT.STATUS.ne("archived"))
                .forUpdate()
                .fetchOne();
        if (current == null) throw new EditorDocumentNotFoundException();
        long currentRevision = current.get(EDITOR_DOCUMENT.CURRENT_REVISION_NO);
        if (currentRevision != command.expectedRevisionNo()) {
            throw new EditorRevisionConflictException(currentRevision);
        }
        UUID revisionId = database.select(EDITOR_REVISION.EDITOR_REVISION_ID)
                .from(EDITOR_REVISION)
                .where(EDITOR_REVISION.EDITOR_DOCUMENT_ID.eq(command.editorDocumentId()))
                .and(EDITOR_REVISION.REVISION_NO.eq(currentRevision))
                .fetchOne(EDITOR_REVISION.EDITOR_REVISION_ID);
        if (revisionId == null) throw new IllegalStateException("current_editor_revision_missing");

        UUID confirmationId = UUID.randomUUID();
        UUID snapshotId = UUID.randomUUID();
        OffsetDateTime now = OffsetDateTime.now();
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
        // 冻结的是投影后的完整文档，不是指向可变草稿 JSON 的引用。
        var frozen = objectMapper.createObjectNode();
        frozen.put("editorModel", "master-overrides-v1");
        frozen.put("schemaVersion", command.schemaVersion());
        frozen.put("sourceRevisionNo", currentRevision);
        frozen.put("variantKey", command.variantKey());
        frozen.put("audience", command.audience());
        frozen.set("projectedDoc", projectedContent.masterDoc());
        String frozenJson;
        try {
            frozenJson = objectMapper.writeValueAsString(frozen);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("editor_snapshot_not_serializable", exception);
        }
        database.insertInto(EDITOR_SNAPSHOT)
                .set(EDITOR_SNAPSHOT.EDITOR_SNAPSHOT_ID, snapshotId)
                .set(EDITOR_SNAPSHOT.EDITOR_DOCUMENT_ID, command.editorDocumentId())
                .set(EDITOR_SNAPSHOT.WORKSPACE_ID, command.workspaceId())
                .set(EDITOR_SNAPSHOT.EDITOR_REVISION_ID, revisionId)
                .set(EDITOR_SNAPSHOT.EDITOR_PREVIEW_CONFIRMATION_ID, confirmationId)
                .set(EDITOR_SNAPSHOT.VARIANT_KEY, command.variantKey())
                .set(EDITOR_SNAPSHOT.AUDIENCE, command.audience())
                .set(EDITOR_SNAPSHOT.SCHEMA_VERSION, command.schemaVersion())
                .set(EDITOR_SNAPSHOT.FROZEN_CONTENT_JSON, JSON.valueOf(frozenJson))
                .set(EDITOR_SNAPSHOT.CONTENT_HASH, projectedContent.contentHash())
                .set(EDITOR_SNAPSHOT.CREATED_AT, now)
                .execute();
        return new EditorSnapshot(
                snapshotId, command.editorDocumentId(), revisionId, currentRevision, command.variantKey(),
                command.audience(), command.schemaVersion(), frozen, projectedContent.contentHash());
    }

    private void insertVariant(UUID documentId, UUID workspaceId, String key, String name, short order, OffsetDateTime now) {
        database.insertInto(EDITOR_VARIANT)
                .set(EDITOR_VARIANT.EDITOR_DOCUMENT_ID, documentId)
                .set(EDITOR_VARIANT.WORKSPACE_ID, workspaceId)
                .set(EDITOR_VARIANT.VARIANT_KEY, key)
                .set(EDITOR_VARIANT.DISPLAY_NAME, name)
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
            ValidatedEditorContent content,
            OffsetDateTime now) {
        database.insertInto(EDITOR_REVISION)
                .set(EDITOR_REVISION.EDITOR_REVISION_ID, revisionId)
                .set(EDITOR_REVISION.EDITOR_DOCUMENT_ID, documentId)
                .set(EDITOR_REVISION.WORKSPACE_ID, workspaceId)
                .set(EDITOR_REVISION.REVISION_NO, revisionNo)
                .set(EDITOR_REVISION.EDITOR_MODEL, "master-overrides-v1")
                .set(EDITOR_REVISION.SCHEMA_VERSION, content.schemaVersion())
                .set(EDITOR_REVISION.MASTER_DOC_JSON, JSON.valueOf(content.masterDocJson()))
                .set(EDITOR_REVISION.VERSION_OVERRIDES_JSON, JSON.valueOf(content.versionOverridesJson()))
                .set(EDITOR_REVISION.CONTENT_HASH, content.contentHash())
                .set(EDITOR_REVISION.CREATED_BY, actorUserId)
                .set(EDITOR_REVISION.CREATED_AT, now)
                .execute();
    }

    private EditorDraft toDraft(
            UUID documentId,
            UUID workspaceId,
            String kind,
            String title,
            UUID revisionId,
            long revisionNo,
            ValidatedEditorContent content) {
        return new EditorDraft(
                documentId, workspaceId, kind, title, revisionId, revisionNo, content.schemaVersion(),
                content.masterDoc(), content.versionOverrides(), content.contentHash());
    }

    private com.fasterxml.jackson.databind.JsonNode parse(JSON json) {
        try {
            return objectMapper.readTree(json.data());
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("stored_editor_json_invalid", exception);
        }
    }
}
