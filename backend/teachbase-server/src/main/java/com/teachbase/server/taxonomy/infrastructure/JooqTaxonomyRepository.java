package com.teachbase.server.taxonomy.infrastructure;

import static com.teachbase.jooq.tables.QuestionTaxonomyLink.QUESTION_TAXONOMY_LINK;
import static com.teachbase.jooq.tables.TaxonomyAlias.TAXONOMY_ALIAS;
import static com.teachbase.jooq.tables.TaxonomyNode.TAXONOMY_NODE;
import static com.teachbase.jooq.tables.TaxonomyVersion.TAXONOMY_VERSION;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.taxonomy.api.QuestionTaxonomyLinkResponse;
import com.teachbase.server.taxonomy.api.TaxonomyNodeResponse;
import com.teachbase.server.taxonomy.api.TaxonomyVersionResponse;
import com.teachbase.server.taxonomy.application.TaxonomyRepository;
import com.teachbase.server.taxonomy.application.TaxonomyValidationException;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.UUID;
import org.jooq.DSLContext;
import org.jooq.JSON;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Repository;

/** jOOQ adapter for draft construction, atomic activation, and version-pinned links. */
@Repository
class JooqTaxonomyRepository implements TaxonomyRepository {

    private final DSLContext database;
    private final ObjectMapper objectMapper;

    JooqTaxonomyRepository(DSLContext database, ObjectMapper objectMapper) {
        this.database = database;
        this.objectMapper = objectMapper;
    }

    @Override
    public TaxonomyVersionResponse createVersion(
            UUID workspaceId,
            UUID actorUserId,
            String taxonomyKey,
            String versionKey,
            String subject,
            String stage,
            int schemaVersion) {
        UUID id = UUID.randomUUID();
        try {
            database.insertInto(TAXONOMY_VERSION)
                    .set(TAXONOMY_VERSION.TAXONOMY_VERSION_ID, id)
                    .set(TAXONOMY_VERSION.WORKSPACE_ID, workspaceId)
                    .set(TAXONOMY_VERSION.TAXONOMY_KEY, taxonomyKey)
                    .set(TAXONOMY_VERSION.VERSION_KEY, versionKey)
                    .set(TAXONOMY_VERSION.SUBJECT, subject)
                    .set(TAXONOMY_VERSION.STAGE, stage)
                    .set(TAXONOMY_VERSION.STATUS, "draft")
                    .set(TAXONOMY_VERSION.SCHEMA_VERSION, schemaVersion)
                    .set(TAXONOMY_VERSION.CREATED_BY, actorUserId)
                    .execute();
        } catch (DataIntegrityViolationException exception) {
            throw new TaxonomyValidationException("taxonomy_version_conflict");
        }
        return new TaxonomyVersionResponse(id, taxonomyKey, versionKey, "draft");
    }

    @Override
    public TaxonomyNodeResponse createNode(
            UUID workspaceId,
            UUID actorUserId,
            UUID taxonomyVersionId,
            String knowledgeCode,
            String displayName,
            UUID parentNodeId,
            int sortOrder,
            JsonNode metadata,
            List<String> aliases) {
        var version = database.selectFrom(TAXONOMY_VERSION)
                .where(TAXONOMY_VERSION.WORKSPACE_ID.eq(workspaceId))
                .and(TAXONOMY_VERSION.TAXONOMY_VERSION_ID.eq(taxonomyVersionId))
                .forUpdate()
                .fetchOne();
        if (version == null) throw new TaxonomyValidationException("taxonomy_version_not_found");
        if (!version.getStatus().equals("draft")) throw new TaxonomyValidationException("taxonomy_version_immutable");
        if (parentNodeId != null && !database.fetchExists(
                TAXONOMY_NODE,
                TAXONOMY_NODE.TAXONOMY_VERSION_ID.eq(taxonomyVersionId)
                        .and(TAXONOMY_NODE.TAXONOMY_NODE_ID.eq(parentNodeId)))) {
            throw new TaxonomyValidationException("taxonomy_parent_not_found");
        }

        UUID nodeId = UUID.randomUUID();
        try {
            database.insertInto(TAXONOMY_NODE)
                    .set(TAXONOMY_NODE.TAXONOMY_NODE_ID, nodeId)
                    .set(TAXONOMY_NODE.TAXONOMY_VERSION_ID, taxonomyVersionId)
                    .set(TAXONOMY_NODE.WORKSPACE_ID, workspaceId)
                    .set(TAXONOMY_NODE.KNOWLEDGE_CODE, knowledgeCode)
                    .set(TAXONOMY_NODE.DISPLAY_NAME, displayName)
                    .set(TAXONOMY_NODE.PARENT_NODE_ID, parentNodeId)
                    .set(TAXONOMY_NODE.SORT_ORDER, sortOrder)
                    .set(TAXONOMY_NODE.METADATA_JSON, json(metadata))
                    .execute();
            for (String alias : aliases) {
                database.insertInto(TAXONOMY_ALIAS)
                        .set(TAXONOMY_ALIAS.TAXONOMY_ALIAS_ID, UUID.randomUUID())
                        .set(TAXONOMY_ALIAS.TAXONOMY_NODE_ID, nodeId)
                        .set(TAXONOMY_ALIAS.TAXONOMY_VERSION_ID, taxonomyVersionId)
                        .set(TAXONOMY_ALIAS.WORKSPACE_ID, workspaceId)
                        .set(TAXONOMY_ALIAS.DISPLAY_ALIAS, alias)
                        .set(TAXONOMY_ALIAS.NORMALIZED_ALIAS, alias.toLowerCase(Locale.ROOT).strip())
                        .execute();
            }
        } catch (DataIntegrityViolationException exception) {
            throw new TaxonomyValidationException("taxonomy_node_conflict");
        }
        return new TaxonomyNodeResponse(nodeId, taxonomyVersionId, knowledgeCode, displayName);
    }

    @Override
    public TaxonomyVersionResponse activate(UUID workspaceId, UUID actorUserId, UUID taxonomyVersionId) {
        var version = database.selectFrom(TAXONOMY_VERSION)
                .where(TAXONOMY_VERSION.WORKSPACE_ID.eq(workspaceId))
                .and(TAXONOMY_VERSION.TAXONOMY_VERSION_ID.eq(taxonomyVersionId))
                .forUpdate()
                .fetchOne();
        if (version == null) throw new TaxonomyValidationException("taxonomy_version_not_found");
        if (!version.getStatus().equals("draft")) throw new TaxonomyValidationException("taxonomy_version_not_draft");
        if (!database.fetchExists(TAXONOMY_NODE, TAXONOMY_NODE.TAXONOMY_VERSION_ID.eq(taxonomyVersionId))) {
            throw new TaxonomyValidationException("taxonomy_version_empty");
        }
        OffsetDateTime now = OffsetDateTime.now();
        database.update(TAXONOMY_VERSION)
                .set(TAXONOMY_VERSION.STATUS, "retired")
                .where(TAXONOMY_VERSION.WORKSPACE_ID.eq(workspaceId))
                .and(TAXONOMY_VERSION.TAXONOMY_KEY.eq(version.getTaxonomyKey()))
                .and(TAXONOMY_VERSION.STATUS.eq("active"))
                .execute();
        database.update(TAXONOMY_VERSION)
                .set(TAXONOMY_VERSION.STATUS, "active")
                .set(TAXONOMY_VERSION.ACTIVATED_AT, now)
                .where(TAXONOMY_VERSION.TAXONOMY_VERSION_ID.eq(taxonomyVersionId))
                .execute();
        return new TaxonomyVersionResponse(
                taxonomyVersionId, version.getTaxonomyKey(), version.getVersionKey(), "active");
    }

    @Override
    public Optional<TaxonomyNodeResponse> resolve(
            UUID workspaceId,
            UUID taxonomyVersionId,
            String codeOrAlias) {
        String normalized = codeOrAlias.toLowerCase(Locale.ROOT).strip();
        return database.selectDistinct(
                        TAXONOMY_NODE.TAXONOMY_NODE_ID,
                        TAXONOMY_NODE.TAXONOMY_VERSION_ID,
                        TAXONOMY_NODE.KNOWLEDGE_CODE,
                        TAXONOMY_NODE.DISPLAY_NAME)
                .from(TAXONOMY_NODE)
                .join(TAXONOMY_VERSION)
                .on(TAXONOMY_VERSION.TAXONOMY_VERSION_ID.eq(TAXONOMY_NODE.TAXONOMY_VERSION_ID))
                .and(TAXONOMY_VERSION.WORKSPACE_ID.eq(TAXONOMY_NODE.WORKSPACE_ID))
                .leftJoin(TAXONOMY_ALIAS)
                .on(TAXONOMY_ALIAS.TAXONOMY_NODE_ID.eq(TAXONOMY_NODE.TAXONOMY_NODE_ID))
                .where(TAXONOMY_NODE.WORKSPACE_ID.eq(workspaceId))
                .and(TAXONOMY_NODE.TAXONOMY_VERSION_ID.eq(taxonomyVersionId))
                .and(TAXONOMY_VERSION.STATUS.eq("active"))
                .and(TAXONOMY_NODE.KNOWLEDGE_CODE.eq(codeOrAlias)
                        .or(TAXONOMY_ALIAS.NORMALIZED_ALIAS.eq(normalized)))
                .fetchOptional(record -> new TaxonomyNodeResponse(
                        record.get(TAXONOMY_NODE.TAXONOMY_NODE_ID),
                        record.get(TAXONOMY_NODE.TAXONOMY_VERSION_ID),
                        record.get(TAXONOMY_NODE.KNOWLEDGE_CODE),
                        record.get(TAXONOMY_NODE.DISPLAY_NAME)));
    }

    @Override
    public QuestionTaxonomyLinkResponse assign(
            UUID workspaceId,
            UUID actorUserId,
            UUID questionId,
            UUID questionRevisionId,
            UUID taxonomyNodeId,
            String relationType,
            String assignmentSource,
            BigDecimal confidence) {
        var node = database.selectFrom(TAXONOMY_NODE)
                .where(TAXONOMY_NODE.WORKSPACE_ID.eq(workspaceId))
                .and(TAXONOMY_NODE.TAXONOMY_NODE_ID.eq(taxonomyNodeId))
                .fetchOne();
        if (node == null) throw new TaxonomyValidationException("taxonomy_node_not_found");
        if (!database.fetchExists(
                TAXONOMY_VERSION,
                TAXONOMY_VERSION.TAXONOMY_VERSION_ID.eq(node.getTaxonomyVersionId())
                        .and(TAXONOMY_VERSION.WORKSPACE_ID.eq(workspaceId))
                        .and(TAXONOMY_VERSION.STATUS.eq("active")))) {
            throw new TaxonomyValidationException("taxonomy_version_not_active");
        }
        UUID id = UUID.randomUUID();
        database.insertInto(QUESTION_TAXONOMY_LINK)
                .set(QUESTION_TAXONOMY_LINK.QUESTION_TAXONOMY_LINK_ID, id)
                .set(QUESTION_TAXONOMY_LINK.WORKSPACE_ID, workspaceId)
                .set(QUESTION_TAXONOMY_LINK.QUESTION_ID, questionId)
                .set(QUESTION_TAXONOMY_LINK.QUESTION_REVISION_ID, questionRevisionId)
                .set(QUESTION_TAXONOMY_LINK.TAXONOMY_NODE_ID, taxonomyNodeId)
                .set(QUESTION_TAXONOMY_LINK.TAXONOMY_VERSION_ID, node.getTaxonomyVersionId())
                .set(QUESTION_TAXONOMY_LINK.RELATION_TYPE, relationType)
                .set(QUESTION_TAXONOMY_LINK.ASSIGNMENT_SOURCE, assignmentSource)
                .set(QUESTION_TAXONOMY_LINK.CONFIDENCE, confidence)
                .set(QUESTION_TAXONOMY_LINK.ASSIGNED_BY, actorUserId)
                .onConflict(
                        QUESTION_TAXONOMY_LINK.QUESTION_REVISION_ID,
                        QUESTION_TAXONOMY_LINK.TAXONOMY_NODE_ID,
                        QUESTION_TAXONOMY_LINK.RELATION_TYPE)
                .doNothing()
                .execute();
        var stored = database.selectFrom(QUESTION_TAXONOMY_LINK)
                .where(QUESTION_TAXONOMY_LINK.QUESTION_REVISION_ID.eq(questionRevisionId))
                .and(QUESTION_TAXONOMY_LINK.TAXONOMY_NODE_ID.eq(taxonomyNodeId))
                .and(QUESTION_TAXONOMY_LINK.RELATION_TYPE.eq(relationType))
                .fetchOne();
        if (stored == null) throw new IllegalStateException("question_taxonomy_assignment_failed");
        return new QuestionTaxonomyLinkResponse(
                stored.getQuestionTaxonomyLinkId(), stored.getQuestionRevisionId(),
                stored.getTaxonomyNodeId(), stored.getRelationType());
    }

    private JSON json(JsonNode value) {
        try {
            return JSON.valueOf(objectMapper.writeValueAsString(value));
        } catch (JsonProcessingException exception) {
            throw new TaxonomyValidationException("taxonomy_metadata_not_serializable");
        }
    }
}
