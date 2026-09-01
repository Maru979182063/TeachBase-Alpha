package com.teachbase.server.exporting.application;

import java.util.UUID;

/**
 * 中文维护说明：本文件属于稳定导出与渲染队列模块的业务规则与事务编排层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Leased queue item containing the worker ownership and attempt identity.
 */
public record ExportWorkItem(
        UUID exportRequestId,
        UUID workspaceId,
        UUID editorSnapshotId,
        UUID requestedBy,
        String format,
        int attemptNo,
        int maxAttempts,
        String workerId) {
}
