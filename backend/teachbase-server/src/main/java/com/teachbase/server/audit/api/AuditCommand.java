package com.teachbase.server.audit.api;

import java.util.Map;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于审计模块的对外稳定合同层，封装跨层调用参数，不能用它绕过对应应用服务的校验。
 *
 * 英文术语对照：Immutable business-event command recorded in the caller's transaction.
 */
public record AuditCommand(
        UUID workspaceId,
        UUID actorUserId,
        String eventType,
        String aggregateType,
        UUID aggregateId,
        Map<String, Object> payload) {
}
