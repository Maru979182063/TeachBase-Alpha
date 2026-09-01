package com.teachbase.server.releaseseed.application;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.IOException;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.charset.StandardCharsets;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.stereotype.Component;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承接长任务执行；修改时必须保持租约、重试、清理和幂等语义。
 *
 * 英文术语对照：Non-web command adapter that emits a UTF-8 machine report and closes Spring cleanly.
 */
@Component
@ConditionalOnProperty(prefix = "teachbase.release-seed", name = "mode")
public class ReleaseSeedCommandRunner implements ApplicationRunner {

    private final ReleaseSeedCoordinator coordinator;
    private final ReleaseSeedProperties properties;
    private final ObjectMapper objectMapper;
    private final ConfigurableApplicationContext context;

    public ReleaseSeedCommandRunner(
            ReleaseSeedCoordinator coordinator,
            ReleaseSeedProperties properties,
            ObjectMapper objectMapper,
            ConfigurableApplicationContext context) {
        this.coordinator = coordinator;
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.context = context;
    }

    @Override
    public void run(ApplicationArguments arguments) throws Exception {
        try {
            ObjectNode report = coordinator.execute(properties);
            emit(report);
            SpringApplication.exit(context, () -> 0);
        } catch (RuntimeException exception) {
            ObjectNode failure = objectMapper.createObjectNode();
            failure.put("schemaVersion", "teachbase.release-seed.loader-report.v1");
            failure.put("generatedAt", java.time.OffsetDateTime.now().toString());
            failure.put("status", "failed");
            failure.put("mode", properties.mode() == null ? "" : properties.mode());
            failure.put("errorCode", stableCode(exception));
            failure.put("reportUsesAbsolutePathsAsInputContract", false);
            emit(failure);
            throw exception;
        }
    }

    private void emit(ObjectNode report) {
        try {
            byte[] bytes = objectMapper.writerWithDefaultPrettyPrinter().writeValueAsBytes(report);
            if (properties.reportPath() != null) atomicWrite(properties.reportPath(), bytes);
            System.out.write(bytes);
            System.out.write('\n');
            System.out.flush();
        } catch (IOException exception) {
            throw new ReleaseSeedValidationException("release_seed_report_write_failed", exception);
        }
    }

    private void atomicWrite(Path requested, byte[] bytes) throws IOException {
        Path target = requested.toAbsolutePath().normalize();
        Path parent = target.getParent();
        if (parent == null) throw new IOException("report_parent_missing");
        Files.createDirectories(parent);
        Path temp = Files.createTempFile(parent, ".release-seed-report-", ".tmp");
        try {
            Files.write(temp, bytes);
            try {
                Files.move(temp, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            } catch (AtomicMoveNotSupportedException exception) {
                throw new IOException("atomic_report_replace_unsupported", exception);
            }
        } finally {
            Files.deleteIfExists(temp);
        }
    }

    private String stableCode(RuntimeException exception) {
        String message = exception.getMessage();
        return message != null && message.matches("[a-z0-9_:-]+") ? message : "release_seed_command_failed";
    }
}
