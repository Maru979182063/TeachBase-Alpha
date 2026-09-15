package com.teachbase.server.governanceprojection.infrastructure;

import java.lang.management.ManagementFactory;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

/** 中文维护说明：所有默认值都适合小型 PostgreSQL poller，不引入外部消息中间件。 */
@ConfigurationProperties("teachbase.governance-projection")
public record GovernanceProjectionProperties(
        boolean enabled,
        String workerId,
        Duration pollDelay,
        Duration leaseDuration,
        Duration retryDelay,
        Integer batchSize) {

    public String effectiveWorkerId() {
        if (workerId != null && !workerId.isBlank()) return workerId.trim();
        String host;
        try {
            host = InetAddress.getLocalHost().getHostName();
        } catch (UnknownHostException exception) {
            host = "unknown-host";
        }
        return ("governance-" + host + "-" + ManagementFactory.getRuntimeMXBean().getPid())
                .replaceAll("[^A-Za-z0-9._-]", "_");
    }

    public Duration effectiveLeaseDuration() {
        return positive(leaseDuration, Duration.ofSeconds(30));
    }

    public Duration effectiveRetryDelay() {
        return positive(retryDelay, Duration.ofSeconds(5));
    }

    public int effectiveBatchSize() {
        return batchSize == null ? 50 : Math.max(1, Math.min(500, batchSize));
    }

    private Duration positive(Duration value, Duration fallback) {
        return value == null || value.isZero() || value.isNegative() ? fallback : value;
    }
}
