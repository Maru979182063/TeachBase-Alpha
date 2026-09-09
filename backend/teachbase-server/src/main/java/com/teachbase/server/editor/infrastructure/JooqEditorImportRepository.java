package com.teachbase.server.editor.infrastructure;

import static com.teachbase.jooq.tables.EditorDocument.EDITOR_DOCUMENT;
import static com.teachbase.jooq.tables.EditorRevision.EDITOR_REVISION;
import static com.teachbase.jooq.tables.EditorVariant.EDITOR_VARIANT;
import static com.teachbase.jooq.tables.EditorWorkingDraft.EDITOR_WORKING_DRAFT;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.teachbase.server.editor.api.EditorImportCommand;
import com.teachbase.server.editor.api.EditorImportResult;
import com.teachbase.server.editor.application.EditorContentValidationException;
import com.teachbase.server.editor.application.EditorImportRepository;
import com.teachbase.server.editor.application.ValidatedEditorContent;
import java.time.OffsetDateTime;
import java.util.UUID;
import org.jooq.DSLContext;
import org.jooq.JSON;
import org.springframework.stereotype.Repository;

/**
 * 中文维护说明：根记录行锁串行化 revision number；已有未提交人工草稿时拒绝导入覆盖，
 * 新导入 revision 只在草稿与当前基线一致时同步 working draft。
 */
@Repository
class JooqEditorImportRepository implements EditorImportRepository {

    private final DSLContext database;
    private final ObjectMapper objectMapper;

    JooqEditorImportRepository(DSLContext database, ObjectMapper objectMapper) {
        this.database = database;
        this.objectMapper = objectMapper;
    }

    @Override
    public EditorImportResult importFrozen(EditorImportCommand command, ValidatedEditorContent content) {
        UUID candidate = UUID.randomUUID();
        OffsetDateTime now = OffsetDateTime.now();
        int created = database.insertInto(EDITOR_DOCUMENT)
                .set(EDITOR_DOCUMENT.EDITOR_DOCUMENT_ID, candidate)
                .set(EDITOR_DOCUMENT.WORKSPACE_ID, command.workspaceId())
                .set(EDITOR_DOCUMENT.IMPORT_IDENTITY_KEY, command.importDocumentKey())
                .set(EDITOR_DOCUMENT.DOCUMENT_KIND, command.documentKind())
                .set(EDITOR_DOCUMENT.TITLE, command.title())
                .set(EDITOR_DOCUMENT.STATUS, "draft")
                .set(EDITOR_DOCUMENT.CURRENT_REVISION_NO, 0L)
                .set(EDITOR_DOCUMENT.WRITER_MODE, "working_draft")
                .set(EDITOR_DOCUMENT.CREATED_BY, command.actorUserId())
                .set(EDITOR_DOCUMENT.UPDATED_BY, command.actorUserId())
                .set(EDITOR_DOCUMENT.CREATED_AT, now)
                .set(EDITOR_DOCUMENT.UPDATED_AT, now)
                .onConflictDoNothing()
                .execute();
        var document = database.selectFrom(EDITOR_DOCUMENT)
                .where(EDITOR_DOCUMENT.WORKSPACE_ID.eq(command.workspaceId()))
                .and(EDITOR_DOCUMENT.IMPORT_IDENTITY_KEY.eq(command.importDocumentKey()))
                .forUpdate()
                .fetchOne();
        if (document == null) throw new IllegalStateException("editor_import_identity_missing");
        if (!document.getDocumentKind().equals(command.documentKind())) {
            throw new EditorContentValidationException("editor_import_document_kind_conflict");
        }
        if (created == 1) insertVariants(document.getEditorDocumentId(), command.workspaceId(), now);

        var reusable = database.selectFrom(EDITOR_REVISION)
                .where(EDITOR_REVISION.EDITOR_DOCUMENT_ID.eq(document.getEditorDocumentId()))
                .and(EDITOR_REVISION.CONTENT_HASH.eq(content.contentHash()))
                .orderBy(EDITOR_REVISION.REVISION_NO.asc())
                .limit(1)
                .fetchOne();
        if (reusable != null) {
            return new EditorImportResult(
                    document.getEditorDocumentId(), reusable.getEditorRevisionId(), reusable.getRevisionNo(),
                    reusable.getContentHash(), created == 1, false);
        }

        assertDraftIsClean(document.getEditorDocumentId(), document.getCurrentRevisionNo());
        long revisionNo = document.getCurrentRevisionNo() + 1;
        UUID revisionId = UUID.randomUUID();
        database.insertInto(EDITOR_REVISION)
                .set(EDITOR_REVISION.EDITOR_REVISION_ID, revisionId)
                .set(EDITOR_REVISION.EDITOR_DOCUMENT_ID, document.getEditorDocumentId())
                .set(EDITOR_REVISION.WORKSPACE_ID, command.workspaceId())
                .set(EDITOR_REVISION.REVISION_NO, revisionNo)
                .set(EDITOR_REVISION.EDITOR_MODEL, "master-overrides-v1")
                .set(EDITOR_REVISION.SCHEMA_VERSION, content.schemaVersion())
                .set(EDITOR_REVISION.MASTER_DOC_JSON, JSON.valueOf(content.masterDocJson()))
                .set(EDITOR_REVISION.VERSION_OVERRIDES_JSON, JSON.valueOf(content.versionOverridesJson()))
                .set(EDITOR_REVISION.CONTENT_HASH, content.contentHash())
                .set(EDITOR_REVISION.CREATED_BY, command.actorUserId())
                .set(EDITOR_REVISION.CREATED_AT, now)
                .execute();
        database.update(EDITOR_DOCUMENT)
                .set(EDITOR_DOCUMENT.CURRENT_REVISION_NO, revisionNo)
                .set(EDITOR_DOCUMENT.TITLE, command.title())
                .set(EDITOR_DOCUMENT.UPDATED_BY, command.actorUserId())
                .set(EDITOR_DOCUMENT.UPDATED_AT, now)
                .where(EDITOR_DOCUMENT.EDITOR_DOCUMENT_ID.eq(document.getEditorDocumentId()))
                .execute();
        upsertWorkingDraft(command, content, document.getEditorDocumentId(), revisionId, now);
        return new EditorImportResult(
                document.getEditorDocumentId(), revisionId, revisionNo, content.contentHash(), created == 1, true);
    }

    private void assertDraftIsClean(UUID documentId, long currentRevisionNo) {
        if (currentRevisionNo == 0) return;
        var state = database.select(
                        EDITOR_WORKING_DRAFT.BASE_REVISION_ID,
                        EDITOR_WORKING_DRAFT.CONTENT_HASH,
                        EDITOR_REVISION.EDITOR_REVISION_ID,
                        EDITOR_REVISION.CONTENT_HASH)
                .from(EDITOR_WORKING_DRAFT)
                .join(EDITOR_REVISION).on(EDITOR_REVISION.EDITOR_DOCUMENT_ID.eq(documentId))
                .and(EDITOR_REVISION.REVISION_NO.eq(currentRevisionNo))
                .where(EDITOR_WORKING_DRAFT.EDITOR_DOCUMENT_ID.eq(documentId))
                .fetchOne();
        if (state == null
                || !java.util.Objects.equals(state.get(EDITOR_WORKING_DRAFT.BASE_REVISION_ID),
                        state.get(EDITOR_REVISION.EDITOR_REVISION_ID))
                || !state.get(EDITOR_WORKING_DRAFT.CONTENT_HASH).equals(state.get(EDITOR_REVISION.CONTENT_HASH))) {
            throw new EditorContentValidationException("editor_import_dirty_working_draft_conflict");
        }
    }

    private void upsertWorkingDraft(
            EditorImportCommand command,
            ValidatedEditorContent content,
            UUID documentId,
            UUID revisionId,
            OffsetDateTime now) {
        ObjectNode envelope = objectMapper.createObjectNode();
        envelope.put("editorModel", "master-overrides-v1");
        envelope.put("schemaVersion", content.schemaVersion());
        envelope.set("masterDoc", content.masterDoc());
        envelope.set("versionOverrides", content.versionOverrides());
        String json;
        try {
            json = objectMapper.writeValueAsString(envelope);
        } catch (JsonProcessingException exception) {
            throw new EditorContentValidationException("editor_content_not_serializable");
        }
        int bytes = json.getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
        database.insertInto(EDITOR_WORKING_DRAFT)
                .set(EDITOR_WORKING_DRAFT.EDITOR_DOCUMENT_ID, documentId)
                .set(EDITOR_WORKING_DRAFT.WORKSPACE_ID, command.workspaceId())
                .set(EDITOR_WORKING_DRAFT.BASE_REVISION_ID, revisionId)
                .set(EDITOR_WORKING_DRAFT.DRAFT_VERSION, 1L)
                .set(EDITOR_WORKING_DRAFT.CONTENT_JSON, JSON.valueOf(json))
                .set(EDITOR_WORKING_DRAFT.CONTENT_HASH, content.contentHash())
                .set(EDITOR_WORKING_DRAFT.CONTENT_BYTES, bytes)
                .set(EDITOR_WORKING_DRAFT.UPDATED_BY, command.actorUserId())
                .set(EDITOR_WORKING_DRAFT.UPDATED_AT, now)
                .onConflict(EDITOR_WORKING_DRAFT.EDITOR_DOCUMENT_ID)
                .doUpdate()
                .set(EDITOR_WORKING_DRAFT.BASE_REVISION_ID, revisionId)
                .set(EDITOR_WORKING_DRAFT.DRAFT_VERSION, EDITOR_WORKING_DRAFT.DRAFT_VERSION.plus(1L))
                .set(EDITOR_WORKING_DRAFT.CONTENT_JSON, JSON.valueOf(json))
                .set(EDITOR_WORKING_DRAFT.CONTENT_HASH, content.contentHash())
                .set(EDITOR_WORKING_DRAFT.CONTENT_BYTES, bytes)
                .set(EDITOR_WORKING_DRAFT.UPDATED_BY, command.actorUserId())
                .set(EDITOR_WORKING_DRAFT.UPDATED_AT, now)
                .execute();
    }

    private void insertVariants(UUID documentId, UUID workspaceId, OffsetDateTime now) {
        insertVariant(documentId, workspaceId, "basic", "基础版", (short) 0, now);
        insertVariant(documentId, workspaceId, "advanced", "进阶版", (short) 1, now);
        insertVariant(documentId, workspaceId, "common", "常用版", (short) 2, now);
    }

    private void insertVariant(
            UUID documentId, UUID workspaceId, String key, String name, short order, OffsetDateTime now) {
        database.insertInto(EDITOR_VARIANT)
                .set(EDITOR_VARIANT.EDITOR_DOCUMENT_ID, documentId)
                .set(EDITOR_VARIANT.WORKSPACE_ID, workspaceId)
                .set(EDITOR_VARIANT.VARIANT_KEY, key)
                .set(EDITOR_VARIANT.DISPLAY_NAME, name)
                .set(EDITOR_VARIANT.SORT_ORDER, order)
                .set(EDITOR_VARIANT.CREATED_AT, now)
                .execute();
    }
}
