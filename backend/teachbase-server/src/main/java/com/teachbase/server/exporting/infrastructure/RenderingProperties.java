package com.teachbase.server.exporting.infrastructure;

import java.lang.management.ManagementFactory;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.nio.file.Path;
import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("teachbase.rendering")
/**
 * 中文维护说明：本文件属于稳定导出与渲染队列模块的数据库或外部工具适配层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Validated tool paths, storage root, lease timing, and renderer process limits.
 */
public record RenderingProperties(
        boolean enabled,
        String workerId,
        String pandocPath,
        String typstPath,
        Path storageRoot,
        Duration pollDelay,
        Duration leaseDuration,
        Duration processTimeout) {

    public String effectiveWorkerId() {
        if (workerId != null && !workerId.isBlank()) return workerId.trim();
        String host;
        try {
            host = InetAddress.getLocalHost().getHostName();
        } catch (UnknownHostException exception) {
            host = "unknown-host";
        }
        return (host + "-" + ManagementFactory.getRuntimeMXBean().getPid()).replaceAll("[^A-Za-z0-9._-]", "_");
    }
}
