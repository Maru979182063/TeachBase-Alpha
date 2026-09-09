package com.teachbase.server.canonicalimport.infrastructure;

import static com.teachbase.jooq.tables.CanonicalImportOperation.CANONICAL_IMPORT_OPERATION;
import static com.teachbase.jooq.tables.CanonicalImportRequest.CANONICAL_IMPORT_REQUEST;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.teachbase.server.canonicalimport.application.CanonicalImportConflictException;
import com.teachbase.server.canonicalimport.application.CanonicalImportPlan;
import com.teachbase.server.canonicalimport.application.CanonicalImportRepository;
import com.teachbase.server.canonicalimport.application.ImportOperationOutcome;
import com.teachbase.server.canonicalimport.application.ImportOperationRecord;
import com.teachbase.server.canonicalimport.application.ImportRequestRecord;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;
import org.jooq.DSLContext;
import org.jooq.JSON;
import org.jooq.impl.DSL;
import org.springframework.stereotype.Repository;

/**
 * 中文维护说明：request 行锁只用于租约接管；每个 operation 的领域写入与 complete
 * 由上层短事务包裹，避免把整包导入锁在一个长事务里。
 */
@Repository
class JooqCanonicalImportRepository implements CanonicalImportRepository {

    private final DSLContext database;
    private final ObjectMapper objectMapper;

    JooqCanonicalImportRepository(DSLContext database, ObjectMapper objectMapper) {
        this.database = database;
        this.objectMapper = objectMapper;
    }

    @Override
    public ValidationSaveResult saveValidation(UUID workspaceId, UUID actorUserId, CanonicalImportPlan plan) {
        UUID requestId = UUID.randomUUID();
        OffsetDateTime now = OffsetDateTime.now();
        int inserted = database.insertInto(CANONICAL_IMPORT_REQUEST)
                .set(CANONICAL_IMPORT_REQUEST.IMPORT_REQUEST_ID, requestId)
                .set(CANONICAL_IMPORT_REQUEST.WORKSPACE_ID, workspaceId)
                .set(CANONICAL_IMPORT_REQUEST.ACTOR_USER_ID, actorUserId)
                .set(CANONICAL_IMPORT_REQUEST.PRODUCER, plan.producer())
                .set(CANONICAL_IMPORT_REQUEST.CONTRACT_VERSION, plan.contractVersion())
                .set(CANONICAL_IMPORT_REQUEST.PACKAGE_KEY, plan.packageKey())
                .set(CANONICAL_IMPORT_REQUEST.PACKAGE_HASH, plan.packageHash())
                .set(CANONICAL_IMPORT_REQUEST.PACKAGE_JSON, json(plan.canonicalPackage()))
                .set(CANONICAL_IMPORT_REQUEST.EXECUTION_PLAN_JSON, json(objectMapper.valueToTree(plan.operations())))
                .set(CANONICAL_IMPORT_REQUEST.STATUS, "validated")
                .set(CANONICAL_IMPORT_REQUEST.OPERATION_COUNT, plan.operations().size())
                .set(CANONICAL_IMPORT_REQUEST.CREATED_AT, now)
                .set(CANONICAL_IMPORT_REQUEST.UPDATED_AT, now)
                .onConflict(CANONICAL_IMPORT_REQUEST.WORKSPACE_ID, CANONICAL_IMPORT_REQUEST.PACKAGE_KEY)
                .doNothing()
                .execute();
        if (inserted == 0) {
            var existing = database.selectFrom(CANONICAL_IMPORT_REQUEST)
                    .where(CANONICAL_IMPORT_REQUEST.WORKSPACE_ID.eq(workspaceId))
                    .and(CANONICAL_IMPORT_REQUEST.PACKAGE_KEY.eq(plan.packageKey()))
                    .fetchOne();
            if (existing == null || !existing.getPackageHash().equals(plan.packageHash())) {
                throw new CanonicalImportConflictException("canonical_import_package_key_payload_conflict");
            }
            return new ValidationSaveResult(mapRequest(existing), true);
        }
        for (var operation : plan.operations()) {
            database.insertInto(CANONICAL_IMPORT_OPERATION)
                    .set(CANONICAL_IMPORT_OPERATION.IMPORT_OPERATION_ID, UUID.randomUUID())
                    .set(CANONICAL_IMPORT_OPERATION.IMPORT_REQUEST_ID, requestId)
                    .set(CANONICAL_IMPORT_OPERATION.WORKSPACE_ID, workspaceId)
                    .set(CANONICAL_IMPORT_OPERATION.OPERATION_KEY, operation.operationKey())
                    .set(CANONICAL_IMPORT_OPERATION.OPERATION_TYPE, operation.operationType())
                    .set(CANONICAL_IMPORT_OPERATION.SEQUENCE_NO, operation.sequenceNo())
                    .set(CANONICAL_IMPORT_OPERATION.DEPENDENCIES_JSON, json(objectMapper.valueToTree(operation.dependencies())))
                    .set(CANONICAL_IMPORT_OPERATION.PAYLOAD_JSON, json(operation.payload()))
                    .set(CANONICAL_IMPORT_OPERATION.PAYLOAD_HASH, operation.payloadHash())
                    .set(CANONICAL_IMPORT_OPERATION.STATUS, "pending")
                    .set(CANONICAL_IMPORT_OPERATION.UPDATED_AT, now)
                    .execute();
        }
        return new ValidationSaveResult(requireRequest(requestId, workspaceId), false);
    }

    @Override
    public ImportRequestRecord requireRequest(UUID importRequestId, UUID workspaceId) {
        var record = database.selectFrom(CANONICAL_IMPORT_REQUEST)
                .where(CANONICAL_IMPORT_REQUEST.IMPORT_REQUEST_ID.eq(importRequestId))
                .and(CANONICAL_IMPORT_REQUEST.WORKSPACE_ID.eq(workspaceId))
                .fetchOne();
        if (record == null) throw new CanonicalImportConflictException("canonical_import_request_not_found");
        return mapRequest(record);
    }

    @Override
    public List<ImportOperationRecord> operations(UUID importRequestId, UUID workspaceId) {
        return database.selectFrom(CANONICAL_IMPORT_OPERATION)
                .where(CANONICAL_IMPORT_OPERATION.IMPORT_REQUEST_ID.eq(importRequestId))
                .and(CANONICAL_IMPORT_OPERATION.WORKSPACE_ID.eq(workspaceId))
                .orderBy(CANONICAL_IMPORT_OPERATION.SEQUENCE_NO.asc())
                .fetch(this::mapOperation);
    }

    @Override
    public ImportRequestRecord acquire(UUID importRequestId, UUID workspaceId, UUID workerToken, Duration leaseDuration) {
        var record = database.selectFrom(CANONICAL_IMPORT_REQUEST)
                .where(CANONICAL_IMPORT_REQUEST.IMPORT_REQUEST_ID.eq(importRequestId))
                .and(CANONICAL_IMPORT_REQUEST.WORKSPACE_ID.eq(workspaceId))
                .forUpdate()
                .fetchOne();
        if (record == null) throw new CanonicalImportConflictException("canonical_import_request_not_found");
        OffsetDateTime now = OffsetDateTime.now();
        if ("completed".equals(record.getStatus())) return mapRequest(record);
        if ("importing".equals(record.getStatus()) && record.getLeaseExpiresAt().isAfter(now)) {
            throw new CanonicalImportConflictException("canonical_import_lease_active");
        }
        database.update(CANONICAL_IMPORT_OPERATION)
                .set(CANONICAL_IMPORT_OPERATION.STATUS, "pending")
                .setNull(CANONICAL_IMPORT_OPERATION.ERROR_JSON)
                .set(CANONICAL_IMPORT_OPERATION.UPDATED_AT, now)
                .where(CANONICAL_IMPORT_OPERATION.IMPORT_REQUEST_ID.eq(importRequestId))
                .and(CANONICAL_IMPORT_OPERATION.STATUS.in("running", "failed"))
                .execute();
        database.update(CANONICAL_IMPORT_REQUEST)
                .set(CANONICAL_IMPORT_REQUEST.STATUS, "importing")
                .set(CANONICAL_IMPORT_REQUEST.WORKER_TOKEN, workerToken)
                .set(CANONICAL_IMPORT_REQUEST.LEASE_EXPIRES_AT, now.plus(leaseDuration))
                .set(CANONICAL_IMPORT_REQUEST.ATTEMPT_NO, CANONICAL_IMPORT_REQUEST.ATTEMPT_NO.plus(1))
                .set(CANONICAL_IMPORT_REQUEST.STARTED_AT,
                        record.getStartedAt() == null ? now : record.getStartedAt())
                .setNull(CANONICAL_IMPORT_REQUEST.FAILURE_SUMMARY_JSON)
                .set(CANONICAL_IMPORT_REQUEST.UPDATED_AT, now)
                .where(CANONICAL_IMPORT_REQUEST.IMPORT_REQUEST_ID.eq(importRequestId))
                .execute();
        return requireRequest(importRequestId, workspaceId);
    }

    @Override
    public void markRunning(UUID requestId, UUID workerToken, UUID operationId, Duration leaseDuration) {
        OffsetDateTime now = OffsetDateTime.now();
        var request = database.selectFrom(CANONICAL_IMPORT_REQUEST)
                .where(CANONICAL_IMPORT_REQUEST.IMPORT_REQUEST_ID.eq(requestId))
                .forUpdate()
                .fetchOne();
        if (request == null || !"importing".equals(request.getStatus())
                || !workerToken.equals(request.getWorkerToken())) {
            throw new CanonicalImportConflictException("canonical_import_worker_fenced");
        }
        database.update(CANONICAL_IMPORT_REQUEST)
                .set(CANONICAL_IMPORT_REQUEST.LEASE_EXPIRES_AT, now.plus(leaseDuration))
                .set(CANONICAL_IMPORT_REQUEST.UPDATED_AT, now)
                .where(CANONICAL_IMPORT_REQUEST.IMPORT_REQUEST_ID.eq(requestId))
                .execute();
        int changed = database.update(CANONICAL_IMPORT_OPERATION)
                .set(CANONICAL_IMPORT_OPERATION.STATUS, "running")
                .set(CANONICAL_IMPORT_OPERATION.ATTEMPT_NO, CANONICAL_IMPORT_OPERATION.ATTEMPT_NO.plus(1))
                .set(CANONICAL_IMPORT_OPERATION.STARTED_AT, now)
                .set(CANONICAL_IMPORT_OPERATION.UPDATED_AT, now)
                .where(CANONICAL_IMPORT_OPERATION.IMPORT_OPERATION_ID.eq(operationId))
                .and(CANONICAL_IMPORT_OPERATION.STATUS.in("pending", "failed"))
                .execute();
        if (changed != 1) throw new CanonicalImportConflictException("canonical_import_operation_not_runnable");
    }

    @Override
    public void complete(UUID operationId, ImportOperationOutcome outcome) {
        OffsetDateTime now = OffsetDateTime.now();
        database.update(CANONICAL_IMPORT_OPERATION)
                .set(CANONICAL_IMPORT_OPERATION.STATUS, "completed")
                .set(CANONICAL_IMPORT_OPERATION.TARGET_ID, outcome.targetId())
                .set(CANONICAL_IMPORT_OPERATION.TARGET_REVISION_ID, outcome.targetRevisionId())
                .set(CANONICAL_IMPORT_OPERATION.TARGET_HASH, outcome.targetHash())
                .set(CANONICAL_IMPORT_OPERATION.RESULT_JSON, json(outcome.result()))
                .setNull(CANONICAL_IMPORT_OPERATION.ERROR_JSON)
                .set(CANONICAL_IMPORT_OPERATION.COMPLETED_AT, now)
                .set(CANONICAL_IMPORT_OPERATION.UPDATED_AT, now)
                .where(CANONICAL_IMPORT_OPERATION.IMPORT_OPERATION_ID.eq(operationId))
                .and(CANONICAL_IMPORT_OPERATION.STATUS.eq("running"))
                .execute();
        UUID requestId = database.select(CANONICAL_IMPORT_OPERATION.IMPORT_REQUEST_ID)
                .from(CANONICAL_IMPORT_OPERATION)
                .where(CANONICAL_IMPORT_OPERATION.IMPORT_OPERATION_ID.eq(operationId))
                .fetchOne(CANONICAL_IMPORT_OPERATION.IMPORT_REQUEST_ID);
        database.update(CANONICAL_IMPORT_REQUEST)
                .set(CANONICAL_IMPORT_REQUEST.COMPLETED_OPERATION_COUNT,
                        CANONICAL_IMPORT_REQUEST.COMPLETED_OPERATION_COUNT.plus(1))
                .set(CANONICAL_IMPORT_REQUEST.UPDATED_AT, now)
                .where(CANONICAL_IMPORT_REQUEST.IMPORT_REQUEST_ID.eq(requestId))
                .execute();
    }

    @Override
    public void fail(UUID requestId, UUID operationId, String code, String detail) {
        OffsetDateTime now = OffsetDateTime.now();
        ObjectNode error = objectMapper.createObjectNode().put("code", code).put("detail", detail);
        database.update(CANONICAL_IMPORT_OPERATION)
                .set(CANONICAL_IMPORT_OPERATION.STATUS, "failed")
                .set(CANONICAL_IMPORT_OPERATION.ERROR_JSON, json(error))
                .set(CANONICAL_IMPORT_OPERATION.UPDATED_AT, now)
                .where(CANONICAL_IMPORT_OPERATION.IMPORT_OPERATION_ID.eq(operationId))
                .and(CANONICAL_IMPORT_OPERATION.STATUS.ne("completed"))
                .execute();
        database.update(CANONICAL_IMPORT_REQUEST)
                .set(CANONICAL_IMPORT_REQUEST.STATUS, "failed")
                .setNull(CANONICAL_IMPORT_REQUEST.WORKER_TOKEN)
                .setNull(CANONICAL_IMPORT_REQUEST.LEASE_EXPIRES_AT)
                .set(CANONICAL_IMPORT_REQUEST.FAILURE_SUMMARY_JSON, json(error))
                .set(CANONICAL_IMPORT_REQUEST.UPDATED_AT, now)
                .where(CANONICAL_IMPORT_REQUEST.IMPORT_REQUEST_ID.eq(requestId))
                .execute();
    }

    @Override
    public void completeRequest(UUID requestId, UUID workerToken, String fingerprint) {
        OffsetDateTime now = OffsetDateTime.now();
        database.update(CANONICAL_IMPORT_REQUEST)
                .set(CANONICAL_IMPORT_REQUEST.STATUS, "completed")
                .set(CANONICAL_IMPORT_REQUEST.RESULT_FINGERPRINT, fingerprint)
                .set(CANONICAL_IMPORT_REQUEST.COMPLETED_AT, now)
                .setNull(CANONICAL_IMPORT_REQUEST.WORKER_TOKEN)
                .setNull(CANONICAL_IMPORT_REQUEST.LEASE_EXPIRES_AT)
                .setNull(CANONICAL_IMPORT_REQUEST.FAILURE_SUMMARY_JSON)
                .set(CANONICAL_IMPORT_REQUEST.UPDATED_AT, now)
                .where(CANONICAL_IMPORT_REQUEST.IMPORT_REQUEST_ID.eq(requestId))
                .and(CANONICAL_IMPORT_REQUEST.WORKER_TOKEN.eq(workerToken))
                .and(CANONICAL_IMPORT_REQUEST.COMPLETED_OPERATION_COUNT.eq(CANONICAL_IMPORT_REQUEST.OPERATION_COUNT))
                .execute();
    }

    @Override
    public void assertCompletedTargetsExist(UUID requestId, UUID workspaceId) {
        for (ImportOperationRecord operation : operations(requestId, workspaceId)) {
            if (!"completed".equals(operation.status())) continue;
            boolean exists = switch (operation.operationType()) {
                case "file_reference" -> exists("file_version", "file_version_id", operation.targetId(), workspaceId);
                case "source_document" -> exists("source_document", "source_document_id", operation.targetId(), workspaceId);
                case "source_region" -> database.fetchExists(DSL.selectOne()
                        .from(DSL.table(DSL.name("teachbase_app", "source_region")).as("r"))
                        .join(DSL.table(DSL.name("teachbase_app", "source_document")).as("d"))
                        .on(DSL.field(DSL.name("r", "source_document_id"), UUID.class)
                                .eq(DSL.field(DSL.name("d", "source_document_id"), UUID.class)))
                        .where(DSL.field(DSL.name("r", "source_region_id"), UUID.class).eq(operation.targetId()))
                        .and(DSL.field(DSL.name("d", "workspace_id"), UUID.class).eq(workspaceId)));
                case "question_revision" -> exists("question_revision", "question_revision_id", operation.targetRevisionId(), workspaceId);
                case "question_provenance" -> database.fetchExists(DSL.selectOne()
                        .from(DSL.table(DSL.name("teachbase_app", "question_source_link")))
                        .where(DSL.field(DSL.name("question_revision_id"), UUID.class).eq(operation.targetRevisionId()))
                        .and(DSL.field(DSL.name("workspace_id"), UUID.class).eq(workspaceId))
                        .and(DSL.field(DSL.name("source_evidence_key"), String.class)
                                .eq(operation.result().path("sourceEvidenceKey").asText())));
                case "standard_module_revision" -> exists("standard_module_revision", "standard_module_revision_id", operation.targetRevisionId(), workspaceId);
                case "standard_module_provenance" -> exists("standard_module_source_link", "standard_module_source_link_id", operation.targetId(), workspaceId);
                case "standard_module_file" -> exists("standard_module_file_reference", "standard_module_file_reference_id", operation.targetId(), workspaceId);
                case "taxonomy_assignment" -> existsEitherTaxonomy(operation.targetId(), workspaceId);
                case "review_intent" -> exists("review_case", "review_case_id", operation.targetId(), workspaceId);
                case "editor_revision" -> exists("editor_revision", "editor_revision_id", operation.targetRevisionId(), workspaceId);
                case "handout_composition" -> database.fetchExists(DSL.selectOne()
                        .from(DSL.table(DSL.name("teachbase_app", "handout_edition_revision")))
                        .where(DSL.field(DSL.name("editor_revision_id"), UUID.class).eq(operation.targetRevisionId()))
                        .and(DSL.field(DSL.name("workspace_id"), UUID.class).eq(workspaceId)));
                default -> false;
            };
            if (!exists) {
                throw new CanonicalImportConflictException(
                        "canonical_import_completed_target_missing:" + operation.operationKey());
            }
        }
    }

    private boolean exists(String table, String idColumn, UUID id, UUID workspaceId) {
        return id != null && database.fetchExists(DSL.selectOne()
                .from(DSL.table(DSL.name("teachbase_app", table)))
                .where(DSL.field(DSL.name(idColumn), UUID.class).eq(id))
                .and(DSL.field(DSL.name("workspace_id"), UUID.class).eq(workspaceId)));
    }

    private boolean existsEitherTaxonomy(UUID id, UUID workspaceId) {
        return exists("question_taxonomy_link", "question_taxonomy_link_id", id, workspaceId)
                || exists("standard_module_taxonomy_link", "standard_module_taxonomy_link_id", id, workspaceId);
    }

    private ImportRequestRecord mapRequest(com.teachbase.jooq.tables.records.CanonicalImportRequestRecord r) {
        return new ImportRequestRecord(r.getImportRequestId(), r.getWorkspaceId(), r.getActorUserId(),
                r.getProducer(), r.getContractVersion(), r.getPackageKey(), r.getPackageHash(), node(r.getPackageJson()),
                r.getStatus(), r.getOperationCount(), r.getCompletedOperationCount(), r.getWorkerToken(), r.getAttemptNo(),
                node(r.getFailureSummaryJson()), r.getResultFingerprint(), r.getCreatedAt(), r.getStartedAt(), r.getCompletedAt());
    }

    private ImportOperationRecord mapOperation(com.teachbase.jooq.tables.records.CanonicalImportOperationRecord r) {
        return new ImportOperationRecord(r.getImportOperationId(), r.getImportRequestId(), r.getOperationKey(),
                r.getOperationType(), r.getSequenceNo(), node(r.getDependenciesJson()), node(r.getPayloadJson()),
                r.getPayloadHash(), r.getStatus(), r.getAttemptNo(), r.getTargetId(), r.getTargetRevisionId(),
                r.getTargetHash(), node(r.getResultJson()), node(r.getErrorJson()), r.getStartedAt(), r.getCompletedAt());
    }

    private JSON json(JsonNode value) {
        try {
            return JSON.valueOf(objectMapper.writeValueAsString(value));
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("canonical_import_json_not_serializable", exception);
        }
    }

    private JsonNode node(JSON value) {
        if (value == null) return null;
        try {
            return objectMapper.readTree(value.data());
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("canonical_import_stored_json_invalid", exception);
        }
    }
}
