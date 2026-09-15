package com.teachbase.server.governanceprojection.infrastructure;

import com.teachbase.server.governanceprojection.application.GovernanceProjectionCoordinator;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/** 中文维护说明：JVM 原子位只防止本进程重入，跨进程正确性由 PostgreSQL 租约保证。 */
@Component
@ConditionalOnProperty(
        prefix = "teachbase.governance-projection", name = "enabled", havingValue = "true")
public class GovernanceProjectionWorker {

    private static final Logger logger = LoggerFactory.getLogger(GovernanceProjectionWorker.class);
    private final GovernanceProjectionProperties properties;
    private final GovernanceProjectionCoordinator coordinator;
    private final AtomicBoolean polling = new AtomicBoolean();

    public GovernanceProjectionWorker(
            GovernanceProjectionProperties properties, GovernanceProjectionCoordinator coordinator) {
        this.properties = properties;
        this.coordinator = coordinator;
    }

    @Scheduled(fixedDelayString = "${teachbase.governance-projection.poll-delay:1s}")
    public void poll() {
        if (!polling.compareAndSet(false, true)) return;
        try {
            coordinator.drain(
                    properties.effectiveWorkerId(), properties.effectiveLeaseDuration(),
                    properties.effectiveRetryDelay(), properties.effectiveBatchSize());
        } catch (RuntimeException exception) {
            logger.error("Governance projection worker cycle failed", exception);
        } finally {
            polling.set(false);
        }
    }
}
