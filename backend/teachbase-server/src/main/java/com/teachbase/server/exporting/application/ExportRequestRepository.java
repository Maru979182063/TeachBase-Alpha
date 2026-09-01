package com.teachbase.server.exporting.application;

import java.util.Optional;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于稳定导出与渲染队列模块的业务规则与事务编排层，定义持久化端口，调用方只依赖业务所需的最小能力。
 *
 * 英文术语对照：Admission and status-query port separate from worker execution transitions.
 */
public interface ExportRequestRepository {

    ExportRequestState create(CreateExportCommand command);

    Optional<ExportRequestState> findByIdempotencyKey(UUID workspaceId, String idempotencyKey);

    Optional<ExportRequestDetails> findById(UUID workspaceId, UUID exportRequestId);

    boolean exists(UUID workspaceId, UUID exportRequestId);
}
