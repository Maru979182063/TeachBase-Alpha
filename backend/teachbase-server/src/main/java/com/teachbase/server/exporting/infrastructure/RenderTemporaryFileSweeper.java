package com.teachbase.server.exporting.infrastructure;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.time.Duration;
import java.time.Instant;
import java.util.Comparator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "teachbase.rendering", name = "enabled", havingValue = "true")
/**
 * 中文维护说明：本文件属于稳定导出与渲染队列模块的数据库或外部工具适配层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Removes only stale renderer-owned temporary files beyond the lease safety window.
 */
class RenderTemporaryFileSweeper {

    private static final Logger logger = LoggerFactory.getLogger(RenderTemporaryFileSweeper.class);
    private final RenderingProperties properties;

    RenderTemporaryFileSweeper(RenderingProperties properties) {
        this.properties = properties;
    }

    @EventListener(ApplicationReadyEvent.class)
    void onApplicationReady() {
        sweep();
    }

    @Scheduled(fixedDelayString = "${teachbase.rendering.temp-sweep-delay:10m}")
    void sweep() {
        Path root = properties.storageRoot().toAbsolutePath().normalize().resolve("exports");
        if (!Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS)) return;
        Duration minimumAge = maximum(properties.leaseDuration().multipliedBy(2), properties.processTimeout().multipliedBy(2));
        Instant cutoff = Instant.now().minus(minimumAge);
        try (var paths = Files.walk(root)) {
            paths.filter(path -> isTemporary(path) && isOlderThan(path, cutoff))
                    .sorted(Comparator.reverseOrder())
                    .forEach(path -> deleteSafely(root, path));
        } catch (IOException exception) {
            logger.warn("Unable to scan stale render artifacts", exception);
        }
    }

    private boolean isTemporary(Path path) {
        String name = path.getFileName().toString();
        return name.startsWith(".render-work-") || (name.startsWith(".") && (name.endsWith(".tmp") || name.contains(".tmp.")));
    }

    private boolean isOlderThan(Path path, Instant cutoff) {
        try {
            FileTime modified = Files.getLastModifiedTime(path, LinkOption.NOFOLLOW_LINKS);
            return modified.toInstant().isBefore(cutoff);
        } catch (IOException exception) {
            return false;
        }
    }

    private void deleteSafely(Path root, Path candidate) {
        Path normalized = candidate.toAbsolutePath().normalize();
        if (!normalized.startsWith(root) || normalized.equals(root)) return;
        try {
            if (Files.isDirectory(normalized, LinkOption.NOFOLLOW_LINKS)) {
                try (var nested = Files.walk(normalized)) {
                    nested.sorted(Comparator.reverseOrder()).forEach(this::deleteOne);
                }
            } else {
                Files.deleteIfExists(normalized);
            }
        } catch (IOException exception) {
            logger.warn("Unable to remove stale render artifact", exception);
        }
    }

    private void deleteOne(Path path) {
        try {
            Files.deleteIfExists(path);
        } catch (IOException exception) {
            logger.warn("Unable to remove stale render artifact", exception);
        }
    }

    private Duration maximum(Duration left, Duration right) {
        return left.compareTo(right) >= 0 ? left : right;
    }
}
