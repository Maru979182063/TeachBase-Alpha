package com.teachbase.server.exporting.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Duration;
import java.util.Optional;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于稳定导出与渲染队列模块的业务规则与事务编排层，定义持久化端口，调用方只依赖业务所需的最小能力。
 * Durable queue port. Implementations must claim with skip-locked semantics and
 * reject heartbeat/completion calls from a worker that no longer owns the lease.
 */
public interface ExportExecutionRepository {

    Optional<ExportWorkItem> claimNext(String workerId, Duration leaseDuration);

    boolean heartbeat(ExportWorkItem item, Duration leaseDuration);

    void complete(
            ExportWorkItem item,
            UUID fileVersionId,
            String rendererVersion,
            JsonNode renderSourceEnvelope,
            String renderSourceHash,
            String outputStorageKey,
            String outputSha256);

    String fail(ExportWorkItem item, String errorCode, boolean retryable);
}
