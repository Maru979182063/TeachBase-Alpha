package com.teachbase.server.exporting.infrastructure;

import com.teachbase.server.editor.api.EditorSnapshotDirectory;
import com.teachbase.server.exporting.application.ExportWorkItem;
import java.io.IOException;
import java.nio.file.Files;
import java.time.Duration;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "teachbase.rendering", name = "enabled", havingValue = "true")
/**
 * 中文维护说明：本文件属于稳定导出与渲染队列模块的数据库或外部工具适配层，承接长任务执行；修改时必须保持租约、重试、清理和幂等语义。
 * Polling worker for durable render jobs.
 *
 * <p>The database lease is authoritative. The local atomic flag only prevents two
 * scheduler callbacks in this JVM from draining the queue simultaneously.</p>
 */
class ExportWorker {

    private static final Logger logger = LoggerFactory.getLogger(ExportWorker.class);
    private final RenderingProperties properties;
    private final ExportExecutionCoordinator coordinator;
    private final EditorSnapshotDirectory snapshots;
    private final PandocDocumentRenderer renderer;
    private final AtomicBoolean polling = new AtomicBoolean();

    ExportWorker(
            RenderingProperties properties,
            ExportExecutionCoordinator coordinator,
            EditorSnapshotDirectory snapshots,
            PandocDocumentRenderer renderer) {
        this.properties = properties;
        this.coordinator = coordinator;
        this.snapshots = snapshots;
        this.renderer = renderer;
    }

    @Scheduled(fixedDelayString = "${teachbase.rendering.poll-delay:1s}")
    void poll() {
        if (!polling.compareAndSet(false, true)) return;
        try {
            while (coordinator.claimNext(properties.effectiveWorkerId(), properties.leaseDuration())
                    .map(this::execute)
                    .orElse(false)) {
                // 连续排空当前就绪队列，不必为每个任务等待下一次调度周期。
            }
        } finally {
            polling.set(false);
        }
    }

    private boolean execute(ExportWorkItem item) {
        var snapshot = snapshots.find(item.editorSnapshotId(), item.workspaceId());
        if (snapshot.isEmpty()) {
            coordinator.fail(item, "editor_snapshot_not_found", false);
            return true;
        }
        // 在租约到期前提前续约。心跳使用独立事务，避免长时间外部渲染进程
        // 掩盖 worker 已失去任务所有权的事实。
        Duration heartbeatPeriod = properties.leaseDuration().dividedBy(3);
        long heartbeatMillis = Math.max(250, heartbeatPeriod.toMillis());
        try (ScheduledExecutorService heartbeat = Executors.newSingleThreadScheduledExecutor(
                Thread.ofVirtual().name("export-heartbeat-", 0).factory())) {
            heartbeat.scheduleAtFixedRate(
                    () -> heartbeatSafely(item), heartbeatMillis, heartbeatMillis, TimeUnit.MILLISECONDS);
            RenderedArtifact artifact = renderer.render(item, snapshot.get());
            try {
                // 文件登记与队列完成状态在同一事务中提交；若事务失败，
                // 未登记的本地产物必须删除，不能成为孤立文件。
                var registration = coordinator.complete(item, artifact);
                if (!registration.storageKey().equals(artifact.storageKey())) deleteQuietly(artifact.path());
            } catch (RuntimeException exception) {
                deleteQuietly(artifact.path());
                throw exception;
            }
        } catch (RenderExecutionException exception) {
            coordinator.fail(item, exception.code(), exception.retryable());
        } catch (RuntimeException exception) {
            logger.error("Export execution failed for request {}", item.exportRequestId(), exception);
            coordinator.fail(item, "export_worker_internal_error", true);
        }
        return true;
    }

    private void heartbeatSafely(ExportWorkItem item) {
        try {
            if (!coordinator.heartbeat(item, properties.leaseDuration())) {
                logger.warn("Export lease was lost for request {}", item.exportRequestId());
            }
        } catch (RuntimeException exception) {
            logger.warn("Export heartbeat failed for request {}", item.exportRequestId(), exception);
        }
    }

    private void deleteQuietly(java.nio.file.Path path) {
        try {
            Files.deleteIfExists(path);
        } catch (IOException exception) {
            logger.warn("Unable to remove unregistered export artifact", exception);
        }
    }
}
