package com.teachbase.server.audit.infrastructure;

import static com.teachbase.jooq.tables.AuditEvent.AUDIT_EVENT;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import java.time.OffsetDateTime;
import java.util.UUID;
import org.jooq.DSLContext;
import org.jooq.JSON;
import org.springframework.stereotype.Repository;

@Repository
/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，负责落实持久化合同；并发正确性最终由事务、锁和数据库约束共同保证。
 *
 * 英文术语对照：Persists append-only audit events without exposing database records to callers.
 */
class JooqAuditTrail implements AuditTrail {

    private final DSLContext database;
    private final ObjectMapper objectMapper;

    JooqAuditTrail(DSLContext database, ObjectMapper objectMapper) {
        this.database = database;
        this.objectMapper = objectMapper;
    }

    @Override
    public void record(AuditCommand command) {
        database.insertInto(AUDIT_EVENT)
                .set(AUDIT_EVENT.AUDIT_EVENT_ID, UUID.randomUUID())
                .set(AUDIT_EVENT.WORKSPACE_ID, command.workspaceId())
                .set(AUDIT_EVENT.ACTOR_USER_ID, command.actorUserId())
                .set(AUDIT_EVENT.EVENT_TYPE, command.eventType())
                .set(AUDIT_EVENT.AGGREGATE_TYPE, command.aggregateType())
                .set(AUDIT_EVENT.AGGREGATE_ID, command.aggregateId())
                .set(AUDIT_EVENT.PAYLOAD_JSON, toJson(command))
                .set(AUDIT_EVENT.OCCURRED_AT, OffsetDateTime.now())
                .execute();
    }

    private JSON toJson(AuditCommand command) {
        try {
            return JSON.valueOf(objectMapper.writeValueAsString(command.payload()));
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("audit_payload_not_serializable", exception);
        }
    }
}
