package com.teachbase.server.audit.api;

import java.util.Map;
import java.util.UUID;

/** Immutable business-event command recorded in the caller's transaction. */
public record AuditCommand(
        UUID workspaceId,
        UUID actorUserId,
        String eventType,
        String aggregateType,
        UUID aggregateId,
        Map<String, Object> payload) {
}
