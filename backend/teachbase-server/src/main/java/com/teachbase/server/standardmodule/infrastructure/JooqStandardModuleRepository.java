package com.teachbase.server.standardmodule.infrastructure;

import static com.teachbase.jooq.tables.HandoutOccurrence.HANDOUT_OCCURRENCE;
import static com.teachbase.jooq.tables.StandardModule.STANDARD_MODULE;
import static com.teachbase.jooq.tables.StandardModuleFileReference.STANDARD_MODULE_FILE_REFERENCE;
import static com.teachbase.jooq.tables.StandardModuleRevision.STANDARD_MODULE_REVISION;
import static com.teachbase.jooq.tables.StandardModuleSourceLink.STANDARD_MODULE_SOURCE_LINK;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.standardmodule.api.StandardModuleLinkResponse;
import com.teachbase.server.standardmodule.api.StandardModuleResponse;
import com.teachbase.server.standardmodule.api.StandardModuleReviewGateway;
import com.teachbase.server.standardmodule.api.StandardModuleReviewStateException;
import com.teachbase.server.standardmodule.api.StandardModuleReviewTarget;
import com.teachbase.server.standardmodule.api.StandardModuleRevisionDescriptor;
import com.teachbase.server.standardmodule.api.StandardModuleRevisionDirectory;
import com.teachbase.server.standardmodule.application.StandardModuleRepository;
import com.teachbase.server.standardmodule.application.StandardModuleRevisionInput;
import com.teachbase.server.standardmodule.application.StandardModuleValidationException;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.jooq.DSLContext;
import org.jooq.JSON;
import org.springframework.stereotype.Repository;

/**
 * 中文维护说明：用根记录行锁串行化 revision number；数据库唯一约束负责并发内容去重，
 * 所有查询同时限定 workspace，不能仅凭 UUID 穿透租户边界。
 */
@Repository
class JooqStandardModuleRepository implements
        StandardModuleRepository,
        StandardModuleRevisionDirectory,
        StandardModuleReviewGateway {

    private final DSLContext database;
    private final ObjectMapper objectMapper;

    JooqStandardModuleRepository(DSLContext database, ObjectMapper objectMapper) {
        this.database = database;
        this.objectMapper = objectMapper;
    }

    @Override
    public StandardModuleResponse create(StandardModuleRevisionInput input) {
        UUID candidate = UUID.randomUUID();
        OffsetDateTime now = OffsetDateTime.now();
        int inserted = database.insertInto(STANDARD_MODULE)
                .set(STANDARD_MODULE.STANDARD_MODULE_ID, candidate)
                .set(STANDARD_MODULE.WORKSPACE_ID, input.workspaceId())
                .set(STANDARD_MODULE.MODULE_KEY, input.moduleKey())
                .set(STANDARD_MODULE.MODULE_TYPE, input.moduleType())
                .set(STANDARD_MODULE.STATUS, "active")
                .set(STANDARD_MODULE.CURRENT_REVISION_NO, 0L)
                .set(STANDARD_MODULE.CREATED_BY, input.actorUserId())
                .set(STANDARD_MODULE.UPDATED_BY, input.actorUserId())
                .set(STANDARD_MODULE.CREATED_AT, now)
                .set(STANDARD_MODULE.UPDATED_AT, now)
                .onConflict(STANDARD_MODULE.WORKSPACE_ID, STANDARD_MODULE.MODULE_KEY)
                .doNothing()
                .execute();
        var root = database.selectFrom(STANDARD_MODULE)
                .where(STANDARD_MODULE.WORKSPACE_ID.eq(input.workspaceId()))
                .and(STANDARD_MODULE.MODULE_KEY.eq(input.moduleKey()))
                .forUpdate()
                .fetchOne();
        if (root == null) throw new IllegalStateException("standard_module_identity_missing");
        if (!root.getModuleType().equals(input.moduleType())) {
            throw new StandardModuleValidationException("standard_module_type_conflict");
        }
        return append(root.getStandardModuleId(), input, inserted == 1);
    }

    @Override
    public StandardModuleResponse revise(UUID standardModuleId, StandardModuleRevisionInput input) {
        var root = database.selectFrom(STANDARD_MODULE)
                .where(STANDARD_MODULE.STANDARD_MODULE_ID.eq(standardModuleId))
                .and(STANDARD_MODULE.WORKSPACE_ID.eq(input.workspaceId()))
                .and(STANDARD_MODULE.STATUS.ne("archived"))
                .forUpdate()
                .fetchOne();
        if (root == null) throw new StandardModuleValidationException("standard_module_not_found");
        var normalized = new StandardModuleRevisionInput(
                input.workspaceId(), input.actorUserId(), root.getModuleKey(), root.getModuleType(),
                input.title(), input.subject(), input.stage(), input.grade(), input.schemaVersion(),
                input.content(), input.contentHash());
        return append(standardModuleId, normalized, false);
    }

    private StandardModuleResponse append(
            UUID standardModuleId, StandardModuleRevisionInput input, boolean createdModule) {
        var root = database.selectFrom(STANDARD_MODULE)
                .where(STANDARD_MODULE.STANDARD_MODULE_ID.eq(standardModuleId))
                .and(STANDARD_MODULE.WORKSPACE_ID.eq(input.workspaceId()))
                .forUpdate()
                .fetchOne();
        var existing = database.selectFrom(STANDARD_MODULE_REVISION)
                .where(STANDARD_MODULE_REVISION.STANDARD_MODULE_ID.eq(standardModuleId))
                .and(STANDARD_MODULE_REVISION.CONTENT_HASH.eq(input.contentHash()))
                .fetchOne();
        if (existing != null) return response(root, existing, createdModule, false);

        long revisionNo = root.getCurrentRevisionNo() + 1;
        UUID revisionId = UUID.randomUUID();
        OffsetDateTime now = OffsetDateTime.now();
        database.insertInto(STANDARD_MODULE_REVISION)
                .set(STANDARD_MODULE_REVISION.STANDARD_MODULE_REVISION_ID, revisionId)
                .set(STANDARD_MODULE_REVISION.STANDARD_MODULE_ID, standardModuleId)
                .set(STANDARD_MODULE_REVISION.WORKSPACE_ID, input.workspaceId())
                .set(STANDARD_MODULE_REVISION.REVISION_NO, revisionNo)
                .set(STANDARD_MODULE_REVISION.REVIEW_STATUS, "unreviewed")
                .set(STANDARD_MODULE_REVISION.TITLE, input.title())
                .set(STANDARD_MODULE_REVISION.SUBJECT, input.subject())
                .set(STANDARD_MODULE_REVISION.STAGE, input.stage())
                .set(STANDARD_MODULE_REVISION.GRADE, input.grade())
                .set(STANDARD_MODULE_REVISION.SCHEMA_VERSION, input.schemaVersion())
                .set(STANDARD_MODULE_REVISION.CONTENT_JSON, json(input.content()))
                .set(STANDARD_MODULE_REVISION.CONTENT_HASH, input.contentHash())
                .set(STANDARD_MODULE_REVISION.CREATED_BY, input.actorUserId())
                .set(STANDARD_MODULE_REVISION.CREATED_AT, now)
                .execute();
        database.update(STANDARD_MODULE)
                .set(STANDARD_MODULE.CURRENT_REVISION_NO, revisionNo)
                .set(STANDARD_MODULE.UPDATED_BY, input.actorUserId())
                .set(STANDARD_MODULE.UPDATED_AT, now)
                .where(STANDARD_MODULE.STANDARD_MODULE_ID.eq(standardModuleId))
                .execute();
        return response(root, database.selectFrom(STANDARD_MODULE_REVISION)
                .where(STANDARD_MODULE_REVISION.STANDARD_MODULE_REVISION_ID.eq(revisionId)).fetchOne(),
                createdModule, true);
    }

    @Override
    public List<StandardModuleRevisionDescriptor> findAll(UUID workspaceId, List<UUID> revisionIds) {
        if (revisionIds == null || revisionIds.isEmpty()) return List.of();
        var records = database.select(
                        STANDARD_MODULE_REVISION.STANDARD_MODULE_REVISION_ID,
                        STANDARD_MODULE_REVISION.STANDARD_MODULE_ID,
                        STANDARD_MODULE_REVISION.WORKSPACE_ID,
                        STANDARD_MODULE.MODULE_KEY,
                        STANDARD_MODULE.MODULE_TYPE,
                        STANDARD_MODULE_REVISION.REVISION_NO,
                        STANDARD_MODULE_REVISION.REVIEW_STATUS,
                        STANDARD_MODULE_REVISION.CONTENT_JSON,
                        STANDARD_MODULE_REVISION.CONTENT_HASH)
                .from(STANDARD_MODULE_REVISION)
                .join(STANDARD_MODULE).on(STANDARD_MODULE.STANDARD_MODULE_ID
                        .eq(STANDARD_MODULE_REVISION.STANDARD_MODULE_ID))
                .where(STANDARD_MODULE_REVISION.WORKSPACE_ID.eq(workspaceId))
                .and(STANDARD_MODULE_REVISION.STANDARD_MODULE_REVISION_ID.in(revisionIds))
                .fetchMap(STANDARD_MODULE_REVISION.STANDARD_MODULE_REVISION_ID);
        List<StandardModuleRevisionDescriptor> result = new ArrayList<>();
        for (UUID revisionId : revisionIds) {
            var record = records.get(revisionId);
            if (record == null) continue;
            result.add(new StandardModuleRevisionDescriptor(
                    record.get(STANDARD_MODULE_REVISION.STANDARD_MODULE_ID), revisionId, workspaceId,
                    record.get(STANDARD_MODULE.MODULE_KEY), record.get(STANDARD_MODULE.MODULE_TYPE),
                    record.get(STANDARD_MODULE_REVISION.REVISION_NO),
                    record.get(STANDARD_MODULE_REVISION.REVIEW_STATUS),
                    parse(record.get(STANDARD_MODULE_REVISION.CONTENT_JSON)),
                    record.get(STANDARD_MODULE_REVISION.CONTENT_HASH)));
        }
        return List.copyOf(result);
    }

    @Override
    public Optional<StandardModuleReviewTarget> findTarget(UUID workspaceId, UUID revisionId) {
        return database.select(
                        STANDARD_MODULE_REVISION.STANDARD_MODULE_ID,
                        STANDARD_MODULE_REVISION.REVIEW_STATUS,
                        STANDARD_MODULE_REVISION.CONTENT_HASH)
                .from(STANDARD_MODULE_REVISION)
                .where(STANDARD_MODULE_REVISION.WORKSPACE_ID.eq(workspaceId))
                .and(STANDARD_MODULE_REVISION.STANDARD_MODULE_REVISION_ID.eq(revisionId))
                .fetchOptional(record -> new StandardModuleReviewTarget(
                        record.get(STANDARD_MODULE_REVISION.STANDARD_MODULE_ID), revisionId,
                        record.get(STANDARD_MODULE_REVISION.REVIEW_STATUS),
                        record.get(STANDARD_MODULE_REVISION.CONTENT_HASH)));
    }

    @Override
    public void applyDecision(
            UUID workspaceId, UUID actorUserId, UUID revisionId, String expectedHash, String decision) {
        var revision = database.selectFrom(STANDARD_MODULE_REVISION)
                .where(STANDARD_MODULE_REVISION.WORKSPACE_ID.eq(workspaceId))
                .and(STANDARD_MODULE_REVISION.STANDARD_MODULE_REVISION_ID.eq(revisionId))
                .forUpdate()
                .fetchOne();
        if (revision == null) throw new StandardModuleReviewStateException("review_standard_module_revision_not_found");
        if (!revision.getContentHash().equals(expectedHash)) {
            throw new StandardModuleReviewStateException("review_standard_module_content_changed");
        }
        if (!java.util.Set.of("unreviewed", "pending_review").contains(revision.getReviewStatus())) {
            throw new StandardModuleReviewStateException("review_standard_module_already_decided");
        }
        OffsetDateTime now = OffsetDateTime.now();
        database.update(STANDARD_MODULE_REVISION)
                .set(STANDARD_MODULE_REVISION.REVIEW_STATUS, decision)
                .set(STANDARD_MODULE_REVISION.APPROVED_AT, decision.equals("approved") ? now : null)
                .where(STANDARD_MODULE_REVISION.STANDARD_MODULE_REVISION_ID.eq(revisionId))
                .execute();
        var update = database.update(STANDARD_MODULE)
                .set(STANDARD_MODULE.UPDATED_BY, actorUserId)
                .set(STANDARD_MODULE.UPDATED_AT, now);
        if (decision.equals("approved")) update.set(STANDARD_MODULE.APPROVED_REVISION_ID, revisionId);
        update.where(STANDARD_MODULE.STANDARD_MODULE_ID.eq(revision.getStandardModuleId()))
                .and(STANDARD_MODULE.WORKSPACE_ID.eq(workspaceId))
                .execute();
    }

    @Override
    public StandardModuleLinkResponse linkSource(
            UUID workspaceId, UUID revisionId, String evidenceKey, UUID sourceDocumentId,
            UUID sourceRegionId, String sourceRole, JsonNode sourceReference) {
        var target = findAll(workspaceId, List.of(revisionId));
        if (target.size() != 1) throw new StandardModuleValidationException("standard_module_revision_not_found");
        UUID id = UUID.randomUUID();
        int created = database.insertInto(STANDARD_MODULE_SOURCE_LINK)
                .set(STANDARD_MODULE_SOURCE_LINK.STANDARD_MODULE_SOURCE_LINK_ID, id)
                .set(STANDARD_MODULE_SOURCE_LINK.STANDARD_MODULE_ID, target.getFirst().standardModuleId())
                .set(STANDARD_MODULE_SOURCE_LINK.STANDARD_MODULE_REVISION_ID, revisionId)
                .set(STANDARD_MODULE_SOURCE_LINK.WORKSPACE_ID, workspaceId)
                .set(STANDARD_MODULE_SOURCE_LINK.SOURCE_EVIDENCE_KEY, evidenceKey)
                .set(STANDARD_MODULE_SOURCE_LINK.SOURCE_DOCUMENT_ID, sourceDocumentId)
                .set(STANDARD_MODULE_SOURCE_LINK.SOURCE_REGION_ID, sourceRegionId)
                .set(STANDARD_MODULE_SOURCE_LINK.SOURCE_ROLE, sourceRole)
                .set(STANDARD_MODULE_SOURCE_LINK.SOURCE_REF_JSON, json(sourceReference))
                .onConflict(STANDARD_MODULE_SOURCE_LINK.STANDARD_MODULE_REVISION_ID,
                        STANDARD_MODULE_SOURCE_LINK.SOURCE_EVIDENCE_KEY)
                .doNothing()
                .execute();
        var stored = database.selectFrom(STANDARD_MODULE_SOURCE_LINK)
                .where(STANDARD_MODULE_SOURCE_LINK.STANDARD_MODULE_REVISION_ID.eq(revisionId))
                .and(STANDARD_MODULE_SOURCE_LINK.SOURCE_EVIDENCE_KEY.eq(evidenceKey))
                .fetchOne();
        if (stored == null) throw new IllegalStateException("standard_module_source_link_failed");
        if (!java.util.Objects.equals(stored.getSourceDocumentId(), sourceDocumentId)
                || !java.util.Objects.equals(stored.getSourceRegionId(), sourceRegionId)
                || !stored.getSourceRole().equals(sourceRole)
                || !parse(stored.getSourceRefJson()).equals(sourceReference)) {
            throw new StandardModuleValidationException("standard_module_source_evidence_conflict");
        }
        return new StandardModuleLinkResponse(stored.getStandardModuleSourceLinkId(), created == 1);
    }

    @Override
    public StandardModuleLinkResponse linkFile(
            UUID workspaceId, UUID revisionId, UUID fileVersionId, String referenceKey,
            String referenceRole, JsonNode metadata) {
        var target = findAll(workspaceId, List.of(revisionId));
        if (target.size() != 1) throw new StandardModuleValidationException("standard_module_revision_not_found");
        UUID id = UUID.randomUUID();
        int created = database.insertInto(STANDARD_MODULE_FILE_REFERENCE)
                .set(STANDARD_MODULE_FILE_REFERENCE.STANDARD_MODULE_FILE_REFERENCE_ID, id)
                .set(STANDARD_MODULE_FILE_REFERENCE.STANDARD_MODULE_ID, target.getFirst().standardModuleId())
                .set(STANDARD_MODULE_FILE_REFERENCE.STANDARD_MODULE_REVISION_ID, revisionId)
                .set(STANDARD_MODULE_FILE_REFERENCE.WORKSPACE_ID, workspaceId)
                .set(STANDARD_MODULE_FILE_REFERENCE.FILE_VERSION_ID, fileVersionId)
                .set(STANDARD_MODULE_FILE_REFERENCE.REFERENCE_KEY, referenceKey)
                .set(STANDARD_MODULE_FILE_REFERENCE.REFERENCE_ROLE, referenceRole)
                .set(STANDARD_MODULE_FILE_REFERENCE.METADATA_JSON, json(metadata))
                .onConflict(STANDARD_MODULE_FILE_REFERENCE.STANDARD_MODULE_REVISION_ID,
                        STANDARD_MODULE_FILE_REFERENCE.REFERENCE_KEY)
                .doNothing()
                .execute();
        var stored = database.selectFrom(STANDARD_MODULE_FILE_REFERENCE)
                .where(STANDARD_MODULE_FILE_REFERENCE.STANDARD_MODULE_REVISION_ID.eq(revisionId))
                .and(STANDARD_MODULE_FILE_REFERENCE.REFERENCE_KEY.eq(referenceKey))
                .fetchOne();
        if (stored == null) throw new IllegalStateException("standard_module_file_link_failed");
        if (!stored.getFileVersionId().equals(fileVersionId)
                || !stored.getReferenceRole().equals(referenceRole)
                || !parse(stored.getMetadataJson()).equals(metadata)) {
            throw new StandardModuleValidationException("standard_module_file_reference_conflict");
        }
        return new StandardModuleLinkResponse(stored.getStandardModuleFileReferenceId(), created == 1);
    }

    @Override
    public long usageCount(UUID workspaceId, UUID revisionId) {
        return database.fetchCount(HANDOUT_OCCURRENCE,
                HANDOUT_OCCURRENCE.WORKSPACE_ID.eq(workspaceId)
                        .and(HANDOUT_OCCURRENCE.STANDARD_MODULE_REVISION_ID.eq(revisionId)));
    }

    private StandardModuleResponse response(
            com.teachbase.jooq.tables.records.StandardModuleRecord root,
            com.teachbase.jooq.tables.records.StandardModuleRevisionRecord revision,
            boolean createdModule, boolean createdRevision) {
        return new StandardModuleResponse(
                root.getStandardModuleId(), revision.getStandardModuleRevisionId(), root.getWorkspaceId(),
                root.getModuleKey(), root.getModuleType(), revision.getRevisionNo(), revision.getReviewStatus(),
                revision.getTitle(), revision.getSubject(), revision.getStage(), revision.getGrade(),
                revision.getSchemaVersion(), parse(revision.getContentJson()), revision.getContentHash(),
                revision.getCreatedAt(), createdModule, createdRevision);
    }

    private JSON json(JsonNode value) {
        try {
            return JSON.valueOf(objectMapper.writeValueAsString(value));
        } catch (JsonProcessingException exception) {
            throw new StandardModuleValidationException("standard_module_json_not_serializable");
        }
    }

    private JsonNode parse(JSON value) {
        try {
            return objectMapper.readTree(value.data());
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("stored_standard_module_json_invalid", exception);
        }
    }
}
