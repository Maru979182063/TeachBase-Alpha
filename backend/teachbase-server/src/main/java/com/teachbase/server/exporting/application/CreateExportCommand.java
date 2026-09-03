package com.teachbase.server.exporting.application;

import java.util.UUID;

/**
 * 中文维护说明：本文件属于稳定导出与渲染队列模块的业务规则与事务编排层，封装跨层调用参数，不能用它绕过对应应用服务的校验。
 *
 * 英文术语对照：Application command for workspace-scoped export admission.
 */
public record CreateExportCommand(
        UUID workspaceId,
        UUID actorUserId,
        UUID editorSnapshotId,
        String format,
        String idempotencyKey,
        UUID retryOfExportRequestId) {
}
