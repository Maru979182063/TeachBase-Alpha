package com.teachbase.server.canonicalimport.application;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

/** 中文维护说明：lease 与故障注入开关；故障注入默认关闭且不得由请求自行开启。 */
@ConfigurationProperties(prefix = "teachbase.canonical-import")
public record CanonicalImportProperties(
        Duration leaseDuration,
        boolean faultInjectionEnabled) {

    public CanonicalImportProperties {
        if (leaseDuration == null) leaseDuration = Duration.ofMinutes(2);
        if (leaseDuration.isNegative() || leaseDuration.isZero()) {
            throw new IllegalArgumentException("canonical_import_lease_duration_invalid");
        }
    }
}
