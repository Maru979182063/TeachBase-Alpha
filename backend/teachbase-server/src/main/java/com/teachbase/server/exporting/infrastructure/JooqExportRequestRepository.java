package com.teachbase.server.exporting.infrastructure;

import static com.teachbase.jooq.tables.ExportRequest.EXPORT_REQUEST;
import static com.teachbase.jooq.tables.ExportAttempt.EXPORT_ATTEMPT;
import static com.teachbase.jooq.tables.ExportFile.EXPORT_FILE;
import static com.teachbase.jooq.tables.FileVersion.FILE_VERSION;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.exporting.application.CreateExportCommand;
import com.teachbase.server.exporting.application.ExportExecutionRepository;
import com.teachbase.server.exporting.application.ExportRequestRepository;
import com.teachbase.server.exporting.application.ExportRequestDetails;
import com.teachbase.server.exporting.application.ExportRequestState;
import com.teachbase.server.exporting.application.ExportWorkItem;
import java.time.Duration;
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
 * 英文术语对照：PostgreSQL queue adapter implementing idempotency, skip-locked claims, leases, and attempts.
 */
class JooqExportRequestRepository implements ExportRequestRepository, ExportExecutionRepository {

    private final DSLContext database;
    private final ObjectMapper objectMapper;

    JooqExportRequestRepository(DSLContext database, ObjectMapper objectMapper) {
        this.database = database;
        this.objectMapper = objectMapper;
    }

    @Override
    public ExportRequestState create(CreateExportCommand command) {
        var existing = findByIdempotencyKey(command.workspaceId(), command.idempotencyKey());
        if (existing.isPresent()) return existing.get();
        UUID exportRequestId = UUID.randomUUID();
        var inserted = database.insertInto(EXPORT_REQUEST)
                .set(EXPORT_REQUEST.EXPORT_REQUEST_ID, exportRequestId)
                .set(EXPORT_REQUEST.WORKSPACE_ID, command.workspaceId())
                .set(EXPORT_REQUEST.EDITOR_SNAPSHOT_ID, command.editorSnapshotId())
                .set(EXPORT_REQUEST.FORMAT, command.format())
                .set(EXPORT_REQUEST.RENDER_CONTRACT_VERSION, 1)
                .set(EXPORT_REQUEST.RENDERER_PROFILE, "teachbase-document-v1")
                .set(EXPORT_REQUEST.STATUS, "queued")
                .set(EXPORT_REQUEST.IDEMPOTENCY_KEY, command.idempotencyKey())
                .set(EXPORT_REQUEST.RETRY_OF_EXPORT_REQUEST_ID, command.retryOfExportRequestId())
                .set(EXPORT_REQUEST.REQUESTED_BY, command.actorUserId())
                .set(EXPORT_REQUEST.REQUESTED_AT, OffsetDateTime.now())
                .onConflict(EXPORT_REQUEST.WORKSPACE_ID, EXPORT_REQUEST.IDEMPOTENCY_KEY)
                .doNothing()
                .returning(EXPORT_REQUEST.EXPORT_REQUEST_ID)
                .fetchOne();
        if (inserted == null) {
            return findByIdempotencyKey(command.workspaceId(), command.idempotencyKey())
                    .orElseThrow(() -> new IllegalStateException("export_idempotency_conflict_without_winner"));
        }
        return new ExportRequestState(
                exportRequestId, command.workspaceId(), command.editorSnapshotId(), command.format(), "queued",
                command.idempotencyKey(), command.retryOfExportRequestId(), true);
    }

    @Override
    public Optional<ExportRequestState> findByIdempotencyKey(UUID workspaceId, String idempotencyKey) {
        return database.selectFrom(EXPORT_REQUEST)
                .where(EXPORT_REQUEST.WORKSPACE_ID.eq(workspaceId))
                .and(EXPORT_REQUEST.IDEMPOTENCY_KEY.eq(idempotencyKey))
                .fetchOptional(record -> new ExportRequestState(
                        record.getExportRequestId(), record.getWorkspaceId(), record.getEditorSnapshotId(),
                        record.getFormat(), record.getStatus(), record.getIdempotencyKey(),
                        record.getRetryOfExportRequestId(), false));
    }

    @Override
    public Optional<ExportRequestDetails> findById(UUID workspaceId, UUID exportRequestId) {
        return database.select(
                        EXPORT_REQUEST.EXPORT_REQUEST_ID,
                        EXPORT_REQUEST.WORKSPACE_ID,
                        EXPORT_REQUEST.EDITOR_SNAPSHOT_ID,
                        EXPORT_REQUEST.FORMAT,
                        EXPORT_REQUEST.STATUS,
                        EXPORT_REQUEST.ATTEMPT_COUNT,
                        EXPORT_REQUEST.MAX_ATTEMPTS,
                        EXPORT_REQUEST.RENDERER_PROFILE,
                        EXPORT_REQUEST.RENDERER_VERSION,
                        EXPORT_REQUEST.ERROR_JSON,
                        EXPORT_REQUEST.REQUESTED_AT,
                        EXPORT_REQUEST.COMPLETED_AT,
                        EXPORT_FILE.FILE_VERSION_ID,
                        FILE_VERSION.STORAGE_KEY,
                        FILE_VERSION.MEDIA_TYPE,
                        FILE_VERSION.SIZE_BYTES,
                        FILE_VERSION.SHA256)
                .from(EXPORT_REQUEST)
                .leftJoin(EXPORT_FILE).on(EXPORT_FILE.EXPORT_REQUEST_ID.eq(EXPORT_REQUEST.EXPORT_REQUEST_ID))
                .leftJoin(FILE_VERSION).on(FILE_VERSION.FILE_VERSION_ID.eq(EXPORT_FILE.FILE_VERSION_ID))
                .where(EXPORT_REQUEST.WORKSPACE_ID.eq(workspaceId))
                .and(EXPORT_REQUEST.EXPORT_REQUEST_ID.eq(exportRequestId))
                .fetchOptional(record -> new ExportRequestDetails(
                        record.get(EXPORT_REQUEST.EXPORT_REQUEST_ID),
                        record.get(EXPORT_REQUEST.WORKSPACE_ID),
                        record.get(EXPORT_REQUEST.EDITOR_SNAPSHOT_ID),
                        record.get(EXPORT_REQUEST.FORMAT),
                        record.get(EXPORT_REQUEST.STATUS),
                        record.get(EXPORT_REQUEST.ATTEMPT_COUNT),
                        record.get(EXPORT_REQUEST.MAX_ATTEMPTS),
                        record.get(EXPORT_REQUEST.RENDERER_PROFILE),
                        record.get(EXPORT_REQUEST.RENDERER_VERSION),
                        parse(record.get(EXPORT_REQUEST.ERROR_JSON)),
                        record.get(EXPORT_REQUEST.REQUESTED_AT),
                        record.get(EXPORT_REQUEST.COMPLETED_AT),
                        record.get(EXPORT_FILE.FILE_VERSION_ID),
                        record.get(FILE_VERSION.STORAGE_KEY),
                        record.get(FILE_VERSION.MEDIA_TYPE),
                        record.get(FILE_VERSION.SIZE_BYTES),
                        record.get(FILE_VERSION.SHA256)));
    }

    @Override
    public boolean exists(UUID workspaceId, UUID exportRequestId) {
        return database.fetchExists(
                database.selectOne().from(EXPORT_REQUEST)
                        .where(EXPORT_REQUEST.WORKSPACE_ID.eq(workspaceId))
                        .and(EXPORT_REQUEST.EXPORT_REQUEST_ID.eq(exportRequestId)));
    }

    @Override
    public Optional<ExportWorkItem> claimNext(String workerId, Duration leaseDuration) {
        recoverExpiredLeases();
        OffsetDateTime now = OffsetDateTime.now();
        var candidate = database.selectFrom(EXPORT_REQUEST)
                .where(EXPORT_REQUEST.STATUS.in("queued", "failed_retryable"))
                .and(EXPORT_REQUEST.AVAILABLE_AT.le(now))
                .and(EXPORT_REQUEST.ATTEMPT_COUNT.lt(EXPORT_REQUEST.MAX_ATTEMPTS))
                .orderBy(EXPORT_REQUEST.AVAILABLE_AT.asc(), EXPORT_REQUEST.REQUESTED_AT.asc())
                .limit(1)
                .forUpdate()
                .skipLocked()
                .fetchOne();
        if (candidate == null) return Optional.empty();
        int attemptNo = candidate.getAttemptCount() + 1;
        UUID attemptId = UUID.randomUUID();
        OffsetDateTime leaseExpiresAt = now.plus(leaseDuration);
        database.update(EXPORT_REQUEST)
                .set(EXPORT_REQUEST.STATUS, "running")
                .set(EXPORT_REQUEST.ATTEMPT_COUNT, attemptNo)
                .set(EXPORT_REQUEST.WORKER_ID, workerId)
                .set(EXPORT_REQUEST.CLAIMED_AT, now)
                .set(EXPORT_REQUEST.HEARTBEAT_AT, now)
                .set(EXPORT_REQUEST.LEASE_EXPIRES_AT, leaseExpiresAt)
                .setNull(EXPORT_REQUEST.ERROR_JSON)
                .where(EXPORT_REQUEST.EXPORT_REQUEST_ID.eq(candidate.getExportRequestId()))
                .execute();
        database.insertInto(EXPORT_ATTEMPT)
                .set(EXPORT_ATTEMPT.EXPORT_ATTEMPT_ID, attemptId)
                .set(EXPORT_ATTEMPT.EXPORT_REQUEST_ID, candidate.getExportRequestId())
                .set(EXPORT_ATTEMPT.WORKSPACE_ID, candidate.getWorkspaceId())
                .set(EXPORT_ATTEMPT.ATTEMPT_NO, attemptNo)
                .set(EXPORT_ATTEMPT.WORKER_ID, workerId)
                .set(EXPORT_ATTEMPT.STATUS, "running")
                .set(EXPORT_ATTEMPT.STARTED_AT, now)
                .set(EXPORT_ATTEMPT.HEARTBEAT_AT, now)
                .execute();
        return Optional.of(new ExportWorkItem(
                candidate.getExportRequestId(),
                candidate.getWorkspaceId(),
                candidate.getEditorSnapshotId(),
                candidate.getRequestedBy(),
                candidate.getFormat(),
                attemptNo,
                candidate.getMaxAttempts(),
                workerId));
    }

    @Override
    public boolean heartbeat(ExportWorkItem item, Duration leaseDuration) {
        OffsetDateTime now = OffsetDateTime.now();
        int updated = database.update(EXPORT_REQUEST)
                .set(EXPORT_REQUEST.HEARTBEAT_AT, now)
                .set(EXPORT_REQUEST.LEASE_EXPIRES_AT, now.plus(leaseDuration))
                .where(EXPORT_REQUEST.EXPORT_REQUEST_ID.eq(item.exportRequestId()))
                .and(EXPORT_REQUEST.STATUS.eq("running"))
                .and(EXPORT_REQUEST.WORKER_ID.eq(item.workerId()))
                .and(EXPORT_REQUEST.ATTEMPT_COUNT.eq(item.attemptNo()))
                .execute();
        if (updated == 1) {
            database.update(EXPORT_ATTEMPT)
                    .set(EXPORT_ATTEMPT.HEARTBEAT_AT, now)
                    .where(EXPORT_ATTEMPT.EXPORT_REQUEST_ID.eq(item.exportRequestId()))
                    .and(EXPORT_ATTEMPT.ATTEMPT_NO.eq(item.attemptNo()))
                    .and(EXPORT_ATTEMPT.STATUS.eq("running"))
                    .execute();
        }
        return updated == 1;
    }

    @Override
    public void complete(
            ExportWorkItem item,
            UUID fileVersionId,
            String rendererVersion,
            JsonNode renderSourceEnvelope,
            String renderSourceHash,
            String outputStorageKey,
            String outputSha256) {
        OffsetDateTime now = OffsetDateTime.now();
        int updated = database.update(EXPORT_REQUEST)
                .set(EXPORT_REQUEST.STATUS, "completed")
                .set(EXPORT_REQUEST.RENDERER_VERSION, rendererVersion)
                .set(EXPORT_REQUEST.RENDER_SOURCE_SCHEMA_VERSION, 1)
                .set(EXPORT_REQUEST.RENDER_SOURCE_JSON, json(renderSourceEnvelope))
                .set(EXPORT_REQUEST.RENDER_SOURCE_HASH, renderSourceHash)
                .set(EXPORT_REQUEST.OUTPUT_STORAGE_KEY, outputStorageKey)
                .set(EXPORT_REQUEST.COMPLETED_AT, now)
                .set(EXPORT_REQUEST.HEARTBEAT_AT, now)
                .set(EXPORT_REQUEST.LEASE_EXPIRES_AT, now)
                .setNull(EXPORT_REQUEST.ERROR_JSON)
                .where(EXPORT_REQUEST.EXPORT_REQUEST_ID.eq(item.exportRequestId()))
                .and(EXPORT_REQUEST.STATUS.eq("running"))
                .and(EXPORT_REQUEST.WORKER_ID.eq(item.workerId()))
                .and(EXPORT_REQUEST.ATTEMPT_COUNT.eq(item.attemptNo()))
                .execute();
        if (updated != 1) throw new IllegalStateException("export_lease_lost_before_completion");
        database.update(EXPORT_ATTEMPT)
                .set(EXPORT_ATTEMPT.STATUS, "completed")
                .set(EXPORT_ATTEMPT.FINISHED_AT, now)
                .set(EXPORT_ATTEMPT.HEARTBEAT_AT, now)
                .set(EXPORT_ATTEMPT.RENDERER_VERSION, rendererVersion)
                .set(EXPORT_ATTEMPT.RENDER_SOURCE_HASH, renderSourceHash)
                .set(EXPORT_ATTEMPT.OUTPUT_SHA256, outputSha256)
                .where(EXPORT_ATTEMPT.EXPORT_REQUEST_ID.eq(item.exportRequestId()))
                .and(EXPORT_ATTEMPT.ATTEMPT_NO.eq(item.attemptNo()))
                .execute();
        database.insertInto(EXPORT_FILE)
                .set(EXPORT_FILE.EXPORT_FILE_ID, UUID.randomUUID())
                .set(EXPORT_FILE.EXPORT_REQUEST_ID, item.exportRequestId())
                .set(EXPORT_FILE.WORKSPACE_ID, item.workspaceId())
                .set(EXPORT_FILE.FILE_VERSION_ID, fileVersionId)
                .set(EXPORT_FILE.CREATED_AT, now)
                .execute();
    }

    @Override
    public String fail(ExportWorkItem item, String errorCode, boolean retryable) {
        OffsetDateTime now = OffsetDateTime.now();
        boolean canRetry = retryable && item.attemptNo() < item.maxAttempts();
        String status = canRetry ? "failed_retryable" : "failed_final";
        int delaySeconds = Math.min(60, 1 << Math.min(item.attemptNo(), 5));
        JSON error = json(errorNode(errorCode, canRetry));
        int updated = database.update(EXPORT_REQUEST)
                .set(EXPORT_REQUEST.STATUS, status)
                .set(EXPORT_REQUEST.ERROR_JSON, error)
                .set(EXPORT_REQUEST.AVAILABLE_AT, canRetry ? now.plusSeconds(delaySeconds) : now)
                .set(EXPORT_REQUEST.HEARTBEAT_AT, now)
                .set(EXPORT_REQUEST.LEASE_EXPIRES_AT, now)
                .where(EXPORT_REQUEST.EXPORT_REQUEST_ID.eq(item.exportRequestId()))
                .and(EXPORT_REQUEST.STATUS.eq("running"))
                .and(EXPORT_REQUEST.WORKER_ID.eq(item.workerId()))
                .and(EXPORT_REQUEST.ATTEMPT_COUNT.eq(item.attemptNo()))
                .execute();
        if (updated == 1) {
            database.update(EXPORT_ATTEMPT)
                    .set(EXPORT_ATTEMPT.STATUS, status)
                    .set(EXPORT_ATTEMPT.FINISHED_AT, now)
                    .set(EXPORT_ATTEMPT.HEARTBEAT_AT, now)
                    .set(EXPORT_ATTEMPT.ERROR_JSON, error)
                    .where(EXPORT_ATTEMPT.EXPORT_REQUEST_ID.eq(item.exportRequestId()))
                    .and(EXPORT_ATTEMPT.ATTEMPT_NO.eq(item.attemptNo()))
                    .execute();
        }
        return status;
    }

    private void recoverExpiredLeases() {
        OffsetDateTime now = OffsetDateTime.now();
        JSON abandonedError = json(errorNode("worker_lease_expired", true));
        database.update(EXPORT_ATTEMPT)
                .set(EXPORT_ATTEMPT.STATUS, "abandoned")
                .set(EXPORT_ATTEMPT.FINISHED_AT, now)
                .set(EXPORT_ATTEMPT.ERROR_JSON, abandonedError)
                .where(EXPORT_ATTEMPT.STATUS.eq("running"))
                .and(EXPORT_ATTEMPT.EXPORT_REQUEST_ID.in(
                        database.select(EXPORT_REQUEST.EXPORT_REQUEST_ID)
                                .from(EXPORT_REQUEST)
                                .where(EXPORT_REQUEST.STATUS.eq("running"))
                                .and(EXPORT_REQUEST.LEASE_EXPIRES_AT.lt(now))))
                .execute();
        database.update(EXPORT_REQUEST)
                .set(EXPORT_REQUEST.STATUS, "failed_retryable")
                .set(EXPORT_REQUEST.ERROR_JSON, abandonedError)
                .set(EXPORT_REQUEST.AVAILABLE_AT, now)
                .where(EXPORT_REQUEST.STATUS.eq("running"))
                .and(EXPORT_REQUEST.LEASE_EXPIRES_AT.lt(now))
                .and(EXPORT_REQUEST.ATTEMPT_COUNT.lt(EXPORT_REQUEST.MAX_ATTEMPTS))
                .execute();
        database.update(EXPORT_REQUEST)
                .set(EXPORT_REQUEST.STATUS, "failed_final")
                .set(EXPORT_REQUEST.ERROR_JSON, json(errorNode("worker_lease_expired", false)))
                .where(EXPORT_REQUEST.STATUS.eq("running"))
                .and(EXPORT_REQUEST.LEASE_EXPIRES_AT.lt(now))
                .and(EXPORT_REQUEST.ATTEMPT_COUNT.ge(EXPORT_REQUEST.MAX_ATTEMPTS))
                .execute();
    }

    private JsonNode errorNode(String code, boolean retryable) {
        var node = objectMapper.createObjectNode();
        node.put("code", code);
        node.put("retryable", retryable);
        return node;
    }

    private JSON json(JsonNode value) {
        try {
            return JSON.valueOf(objectMapper.writeValueAsString(value));
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("export_json_not_serializable", exception);
        }
    }

    private JsonNode parse(JSON value) {
        if (value == null) return null;
        try {
            return objectMapper.readTree(value.data());
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("stored_export_error_json_invalid", exception);
        }
    }
}
