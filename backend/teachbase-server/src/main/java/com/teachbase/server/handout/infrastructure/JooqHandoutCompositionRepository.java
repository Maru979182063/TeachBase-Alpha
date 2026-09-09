package com.teachbase.server.handout.infrastructure;

import static com.teachbase.jooq.tables.EditorRevisionArtifactLink.EDITOR_REVISION_ARTIFACT_LINK;
import static com.teachbase.jooq.tables.HandoutEdition.HANDOUT_EDITION;
import static com.teachbase.jooq.tables.HandoutEditionRevision.HANDOUT_EDITION_REVISION;
import static com.teachbase.jooq.tables.HandoutOccurrence.HANDOUT_OCCURRENCE;
import static com.teachbase.jooq.tables.HandoutOccurrenceIdentity.HANDOUT_OCCURRENCE_IDENTITY;
import static com.teachbase.jooq.tables.HandoutOccurrenceSourceLink.HANDOUT_OCCURRENCE_SOURCE_LINK;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.handout.api.EditorRevisionArtifactInput;
import com.teachbase.server.handout.api.HandoutCompositionResponse;
import com.teachbase.server.handout.api.HandoutEditionResult;
import com.teachbase.server.handout.application.HandoutCompositionRepository;
import com.teachbase.server.handout.application.HandoutValidationException;
import com.teachbase.server.handout.application.ResolvedHandoutEdition;
import com.teachbase.server.handout.application.ResolvedHandoutOccurrence;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.jooq.DSLContext;
import org.jooq.JSON;
import org.springframework.stereotype.Repository;

/**
 * 中文维护说明：以一个事务写入精确 editor revision 的 composition；edition revision 一旦存在，
 * 只有相同 hash 的请求可作为幂等重放，数据库 immutable trigger 拒绝后续改写。
 */
@Repository
class JooqHandoutCompositionRepository implements HandoutCompositionRepository {

    private final DSLContext database;
    private final ObjectMapper objectMapper;

    JooqHandoutCompositionRepository(DSLContext database, ObjectMapper objectMapper) {
        this.database = database;
        this.objectMapper = objectMapper;
    }

    @Override
    public HandoutCompositionResponse create(
            UUID workspaceId,
            UUID actorUserId,
            UUID editorDocumentId,
            UUID editorRevisionId,
            List<ResolvedHandoutEdition> editions,
            List<EditorRevisionArtifactInput> artifacts) {
        Map<String, UUID> editionRevisionIds = new LinkedHashMap<>();
        List<HandoutEditionResult> results = new ArrayList<>();
        for (ResolvedHandoutEdition edition : editions) {
            UUID editionId = ensureEdition(
                    workspaceId, actorUserId, editorDocumentId, edition.editionKey(), edition.editionRole());
            UUID canonicalId = edition.canonicalTeacherEditionKey() == null
                    ? null : editionRevisionIds.get(edition.canonicalTeacherEditionKey());
            if (edition.editionRole().equals("projection") && canonicalId == null) {
                throw new HandoutValidationException("handout_projection_teacher_revision_missing");
            }
            UUID editionRevisionId = UUID.randomUUID();
            OffsetDateTime now = OffsetDateTime.now();
            int inserted = database.insertInto(HANDOUT_EDITION_REVISION)
                    .set(HANDOUT_EDITION_REVISION.HANDOUT_EDITION_REVISION_ID, editionRevisionId)
                    .set(HANDOUT_EDITION_REVISION.HANDOUT_EDITION_ID, editionId)
                    .set(HANDOUT_EDITION_REVISION.EDITOR_DOCUMENT_ID, editorDocumentId)
                    .set(HANDOUT_EDITION_REVISION.EDITOR_REVISION_ID, editorRevisionId)
                    .set(HANDOUT_EDITION_REVISION.WORKSPACE_ID, workspaceId)
                    .set(HANDOUT_EDITION_REVISION.EDITION_ROLE, edition.editionRole())
                    .set(HANDOUT_EDITION_REVISION.CANONICAL_TEACHER_REVISION_ID, canonicalId)
                    .set(HANDOUT_EDITION_REVISION.SCHEMA_VERSION, edition.schemaVersion())
                    .set(HANDOUT_EDITION_REVISION.PROJECTION_RULES_JSON, json(edition.projectionRules()))
                    .set(HANDOUT_EDITION_REVISION.DELTA_JSON, json(edition.delta()))
                    .set(HANDOUT_EDITION_REVISION.CONTENT_HASH, edition.contentHash())
                    .set(HANDOUT_EDITION_REVISION.CREATED_BY, actorUserId)
                    .set(HANDOUT_EDITION_REVISION.CREATED_AT, now)
                    .onConflict(HANDOUT_EDITION_REVISION.HANDOUT_EDITION_ID,
                            HANDOUT_EDITION_REVISION.EDITOR_REVISION_ID)
                    .doNothing()
                    .execute();
            var storedRevision = database.selectFrom(HANDOUT_EDITION_REVISION)
                    .where(HANDOUT_EDITION_REVISION.HANDOUT_EDITION_ID.eq(editionId))
                    .and(HANDOUT_EDITION_REVISION.EDITOR_REVISION_ID.eq(editorRevisionId))
                    .fetchOne();
            if (storedRevision == null) throw new IllegalStateException("handout_edition_revision_creation_failed");
            if (!storedRevision.getContentHash().equals(edition.contentHash())
                    || !java.util.Objects.equals(storedRevision.getCanonicalTeacherRevisionId(), canonicalId)) {
                throw new HandoutValidationException("handout_composition_revision_conflict");
            }
            editionRevisionId = storedRevision.getHandoutEditionRevisionId();
            if (inserted == 0) {
                editionRevisionIds.put(edition.editionKey(), editionRevisionId);
                results.add(result(editionRevisionId, editionId, edition, canonicalId, true));
                continue;
            }
            persistOccurrences(
                    workspaceId, actorUserId, editorDocumentId, editorRevisionId,
                    editionRevisionId, edition.occurrences());
            editionRevisionIds.put(edition.editionKey(), editionRevisionId);
            results.add(result(editionRevisionId, editionId, edition, canonicalId, false));
        }
        persistArtifacts(workspaceId, editorDocumentId, editorRevisionId, artifacts);
        int artifactCount = database.fetchCount(
                EDITOR_REVISION_ARTIFACT_LINK,
                EDITOR_REVISION_ARTIFACT_LINK.WORKSPACE_ID.eq(workspaceId)
                        .and(EDITOR_REVISION_ARTIFACT_LINK.EDITOR_REVISION_ID.eq(editorRevisionId)));
        return new HandoutCompositionResponse(
                editorDocumentId, editorRevisionId, workspaceId, List.copyOf(results), artifactCount);
    }

    private UUID ensureEdition(
            UUID workspaceId, UUID actorUserId, UUID editorDocumentId, String key, String role) {
        UUID candidate = UUID.randomUUID();
        database.insertInto(HANDOUT_EDITION)
                .set(HANDOUT_EDITION.HANDOUT_EDITION_ID, candidate)
                .set(HANDOUT_EDITION.EDITOR_DOCUMENT_ID, editorDocumentId)
                .set(HANDOUT_EDITION.WORKSPACE_ID, workspaceId)
                .set(HANDOUT_EDITION.EDITION_KEY, key)
                .set(HANDOUT_EDITION.EDITION_ROLE, role)
                .set(HANDOUT_EDITION.CREATED_BY, actorUserId)
                .onConflict(HANDOUT_EDITION.EDITOR_DOCUMENT_ID, HANDOUT_EDITION.EDITION_KEY)
                .doNothing()
                .execute();
        var stored = database.selectFrom(HANDOUT_EDITION)
                .where(HANDOUT_EDITION.EDITOR_DOCUMENT_ID.eq(editorDocumentId))
                .and(HANDOUT_EDITION.EDITION_KEY.eq(key))
                .fetchOne();
        if (stored == null) throw new IllegalStateException("handout_edition_creation_failed");
        if (!stored.getWorkspaceId().equals(workspaceId) || !stored.getEditionRole().equals(role)) {
            throw new HandoutValidationException("handout_edition_identity_conflict");
        }
        return stored.getHandoutEditionId();
    }

    private void persistOccurrences(
            UUID workspaceId,
            UUID actorUserId,
            UUID editorDocumentId,
            UUID editorRevisionId,
            UUID editionRevisionId,
            List<ResolvedHandoutOccurrence> occurrences) {
        Map<String, ResolvedHandoutOccurrence> pending = new LinkedHashMap<>();
        occurrences.forEach(value -> pending.put(value.occurrenceKey(), value));
        Map<String, UUID> stored = new LinkedHashMap<>();
        while (!pending.isEmpty()) {
            int before = pending.size();
            var iterator = pending.entrySet().iterator();
            while (iterator.hasNext()) {
                var entry = iterator.next();
                var occurrence = entry.getValue();
                if (occurrence.parentOccurrenceKey() != null
                        && !stored.containsKey(occurrence.parentOccurrenceKey())) continue;
                UUID identityId = ensureOccurrenceIdentity(
                        workspaceId, actorUserId, editorDocumentId, occurrence.occurrenceKey());
                UUID occurrenceId = UUID.randomUUID();
                database.insertInto(HANDOUT_OCCURRENCE)
                        .set(HANDOUT_OCCURRENCE.HANDOUT_OCCURRENCE_ID, occurrenceId)
                        .set(HANDOUT_OCCURRENCE.HANDOUT_OCCURRENCE_IDENTITY_ID, identityId)
                        .set(HANDOUT_OCCURRENCE.HANDOUT_EDITION_REVISION_ID, editionRevisionId)
                        .set(HANDOUT_OCCURRENCE.EDITOR_DOCUMENT_ID, editorDocumentId)
                        .set(HANDOUT_OCCURRENCE.EDITOR_REVISION_ID, editorRevisionId)
                        .set(HANDOUT_OCCURRENCE.WORKSPACE_ID, workspaceId)
                        .set(HANDOUT_OCCURRENCE.PARENT_OCCURRENCE_ID,
                                occurrence.parentOccurrenceKey() == null
                                        ? null : stored.get(occurrence.parentOccurrenceKey()))
                        .set(HANDOUT_OCCURRENCE.POSITION_INDEX, occurrence.positionIndex())
                        .set(HANDOUT_OCCURRENCE.OCCURRENCE_KIND, occurrence.kind())
                        .set(HANDOUT_OCCURRENCE.QUESTION_ID, occurrence.questionId())
                        .set(HANDOUT_OCCURRENCE.QUESTION_REVISION_ID, occurrence.questionRevisionId())
                        .set(HANDOUT_OCCURRENCE.STANDARD_MODULE_ID, occurrence.standardModuleId())
                        .set(HANDOUT_OCCURRENCE.STANDARD_MODULE_REVISION_ID,
                                occurrence.standardModuleRevisionId())
                        .set(HANDOUT_OCCURRENCE.LOCAL_CONTENT_JSON,
                                occurrence.localContent() == null ? null : json(occurrence.localContent()))
                        .set(HANDOUT_OCCURRENCE.ATTRIBUTES_JSON, json(occurrence.attributes()))
                        .set(HANDOUT_OCCURRENCE.CREATED_BY, actorUserId)
                        .execute();
                persistSources(workspaceId, occurrenceId, editionRevisionId, occurrence);
                stored.put(occurrence.occurrenceKey(), occurrenceId);
                iterator.remove();
            }
            if (pending.size() == before) {
                throw new HandoutValidationException("handout_occurrence_hierarchy_unresolvable");
            }
        }
    }

    private UUID ensureOccurrenceIdentity(
            UUID workspaceId, UUID actorUserId, UUID editorDocumentId, String occurrenceKey) {
        UUID candidate = UUID.randomUUID();
        database.insertInto(HANDOUT_OCCURRENCE_IDENTITY)
                .set(HANDOUT_OCCURRENCE_IDENTITY.HANDOUT_OCCURRENCE_IDENTITY_ID, candidate)
                .set(HANDOUT_OCCURRENCE_IDENTITY.EDITOR_DOCUMENT_ID, editorDocumentId)
                .set(HANDOUT_OCCURRENCE_IDENTITY.WORKSPACE_ID, workspaceId)
                .set(HANDOUT_OCCURRENCE_IDENTITY.OCCURRENCE_KEY, occurrenceKey)
                .set(HANDOUT_OCCURRENCE_IDENTITY.CREATED_BY, actorUserId)
                .onConflict(HANDOUT_OCCURRENCE_IDENTITY.EDITOR_DOCUMENT_ID,
                        HANDOUT_OCCURRENCE_IDENTITY.OCCURRENCE_KEY)
                .doNothing()
                .execute();
        var stored = database.selectFrom(HANDOUT_OCCURRENCE_IDENTITY)
                .where(HANDOUT_OCCURRENCE_IDENTITY.EDITOR_DOCUMENT_ID.eq(editorDocumentId))
                .and(HANDOUT_OCCURRENCE_IDENTITY.OCCURRENCE_KEY.eq(occurrenceKey))
                .fetchOne();
        if (stored == null || !stored.getWorkspaceId().equals(workspaceId)) {
            throw new HandoutValidationException("handout_occurrence_identity_conflict");
        }
        return stored.getHandoutOccurrenceIdentityId();
    }

    private void persistSources(
            UUID workspaceId,
            UUID occurrenceId,
            UUID editionRevisionId,
            ResolvedHandoutOccurrence occurrence) {
        for (var source : occurrence.sources()) {
            database.insertInto(HANDOUT_OCCURRENCE_SOURCE_LINK)
                    .set(HANDOUT_OCCURRENCE_SOURCE_LINK.HANDOUT_OCCURRENCE_SOURCE_LINK_ID, UUID.randomUUID())
                    .set(HANDOUT_OCCURRENCE_SOURCE_LINK.HANDOUT_OCCURRENCE_ID, occurrenceId)
                    .set(HANDOUT_OCCURRENCE_SOURCE_LINK.HANDOUT_EDITION_REVISION_ID, editionRevisionId)
                    .set(HANDOUT_OCCURRENCE_SOURCE_LINK.WORKSPACE_ID, workspaceId)
                    .set(HANDOUT_OCCURRENCE_SOURCE_LINK.SOURCE_EVIDENCE_KEY, source.sourceEvidenceKey().trim())
                    .set(HANDOUT_OCCURRENCE_SOURCE_LINK.SOURCE_DOCUMENT_ID, source.sourceDocumentId())
                    .set(HANDOUT_OCCURRENCE_SOURCE_LINK.SOURCE_REGION_ID, source.sourceRegionId())
                    .set(HANDOUT_OCCURRENCE_SOURCE_LINK.SOURCE_ROLE, source.sourceRole().trim())
                    .set(HANDOUT_OCCURRENCE_SOURCE_LINK.SOURCE_REF_JSON, json(source.sourceReference()))
                    .execute();
        }
    }

    private void persistArtifacts(
            UUID workspaceId,
            UUID editorDocumentId,
            UUID editorRevisionId,
            List<EditorRevisionArtifactInput> artifacts) {
        for (var artifact : artifacts) {
            String key = artifact.artifactKey().trim();
            String role = artifact.artifactRole().trim();
            database.insertInto(EDITOR_REVISION_ARTIFACT_LINK)
                    .set(EDITOR_REVISION_ARTIFACT_LINK.EDITOR_REVISION_ARTIFACT_LINK_ID, UUID.randomUUID())
                    .set(EDITOR_REVISION_ARTIFACT_LINK.EDITOR_DOCUMENT_ID, editorDocumentId)
                    .set(EDITOR_REVISION_ARTIFACT_LINK.EDITOR_REVISION_ID, editorRevisionId)
                    .set(EDITOR_REVISION_ARTIFACT_LINK.WORKSPACE_ID, workspaceId)
                    .set(EDITOR_REVISION_ARTIFACT_LINK.ARTIFACT_KEY, key)
                    .set(EDITOR_REVISION_ARTIFACT_LINK.ARTIFACT_ROLE, role)
                    .set(EDITOR_REVISION_ARTIFACT_LINK.FILE_VERSION_ID, artifact.fileVersionId())
                    .set(EDITOR_REVISION_ARTIFACT_LINK.SOURCE_DOCUMENT_ID, artifact.sourceDocumentId())
                    .set(EDITOR_REVISION_ARTIFACT_LINK.METADATA_JSON, json(artifact.metadata()))
                    .onConflict(EDITOR_REVISION_ARTIFACT_LINK.EDITOR_REVISION_ID,
                            EDITOR_REVISION_ARTIFACT_LINK.ARTIFACT_KEY)
                    .doNothing()
                    .execute();
            var stored = database.selectFrom(EDITOR_REVISION_ARTIFACT_LINK)
                    .where(EDITOR_REVISION_ARTIFACT_LINK.EDITOR_REVISION_ID.eq(editorRevisionId))
                    .and(EDITOR_REVISION_ARTIFACT_LINK.ARTIFACT_KEY.eq(key))
                    .fetchOne();
            if (stored == null) throw new IllegalStateException("editor_revision_artifact_link_failed");
            if (!stored.getWorkspaceId().equals(workspaceId)
                    || !stored.getArtifactRole().equals(role)
                    || !stored.getFileVersionId().equals(artifact.fileVersionId())
                    || !java.util.Objects.equals(stored.getSourceDocumentId(), artifact.sourceDocumentId())
                    || !parse(stored.getMetadataJson()).equals(artifact.metadata())) {
                throw new HandoutValidationException("handout_artifact_key_conflict");
            }
        }
    }

    private HandoutEditionResult result(
            UUID revisionId,
            UUID editionId,
            ResolvedHandoutEdition edition,
            UUID canonicalId,
            boolean replayed) {
        int occurrenceCount = database.fetchCount(
                HANDOUT_OCCURRENCE,
                HANDOUT_OCCURRENCE.HANDOUT_EDITION_REVISION_ID.eq(revisionId));
        int sourceCount = database.fetchCount(
                HANDOUT_OCCURRENCE_SOURCE_LINK,
                HANDOUT_OCCURRENCE_SOURCE_LINK.HANDOUT_EDITION_REVISION_ID.eq(revisionId));
        return new HandoutEditionResult(
                editionId, revisionId, edition.editionKey(), edition.editionRole(), canonicalId,
                edition.contentHash(), occurrenceCount, sourceCount, replayed);
    }

    private JSON json(JsonNode value) {
        try {
            return JSON.valueOf(objectMapper.writeValueAsString(value));
        } catch (JsonProcessingException exception) {
            throw new HandoutValidationException("handout_json_not_serializable");
        }
    }

    private JsonNode parse(JSON value) {
        try {
            return objectMapper.readTree(value.data());
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("stored_handout_json_invalid", exception);
        }
    }
}
