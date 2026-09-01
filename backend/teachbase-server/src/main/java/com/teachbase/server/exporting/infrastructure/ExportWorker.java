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
                // Drain the ready queue without waiting for another scheduler tick.
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
        // Renew well before lease expiry. Heartbeat runs in a separate transaction so
        // a long external renderer process does not hide ownership loss.
        Duration heartbeatPeriod = properties.leaseDuration().dividedBy(3);
        long heartbeatMillis = Math.max(250, heartbeatPeriod.toMillis());
        try (ScheduledExecutorService heartbeat = Executors.newSingleThreadScheduledExecutor(
                Thread.ofVirtual().name("export-heartbeat-", 0).factory())) {
            heartbeat.scheduleAtFixedRate(
                    () -> heartbeatSafely(item), heartbeatMillis, heartbeatMillis, TimeUnit.MILLISECONDS);
            RenderedArtifact artifact = renderer.render(item, snapshot.get());
            try {
                // Registration and queue completion are transactional. If they fail,
                // the unregistered local artifact must not survive as orphaned output.
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
