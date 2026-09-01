package com.teachbase.server.exporting.api;

import com.teachbase.server.exporting.application.ExportRequestState;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Admission response distinguishing a new request from an idempotent replay.
 */
public record ExportRequestResponse(
        UUID exportRequestId,
        UUID workspaceId,
        UUID editorSnapshotId,
        String format,
        String status,
        String idempotencyKey,
        UUID retryOfExportRequestId,
        boolean created) {

    static ExportRequestResponse from(ExportRequestState state) {
        return new ExportRequestResponse(
                state.exportRequestId(), state.workspaceId(), state.editorSnapshotId(), state.format(),
                state.status(), state.idempotencyKey(), state.retryOfExportRequestId(), state.created());
    }
}
