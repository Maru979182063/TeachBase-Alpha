package com.teachbase.server.exporting.infrastructure;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/**
 * 中文维护说明：本文件属于稳定导出与渲染队列模块的数据库或外部工具适配层，承接长任务执行；修改时必须保持租约、重试、清理和幂等语义。
 *
 * 英文术语对照：Runs a bounded external renderer process without invoking a platform shell.
 */
final class ExternalToolRunner {

    private static final int MAX_CAPTURE_BYTES = 16 * 1024 * 1024;

    ToolResult run(List<String> command, Path workingDirectory, byte[] stdin, Duration timeout) {
        Process process;
        try {
            process = new ProcessBuilder(command)
                    .directory(workingDirectory.toFile())
                    .redirectErrorStream(false)
                    .start();
        } catch (IOException exception) {
            throw new RenderExecutionException("render_tool_unavailable", true, exception);
        }
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var stdout = executor.submit(() -> process.getInputStream().readNBytes(MAX_CAPTURE_BYTES + 1));
            var stderr = executor.submit(() -> process.getErrorStream().readNBytes(MAX_CAPTURE_BYTES + 1));
            try (var input = process.getOutputStream()) {
                if (stdin != null) input.write(stdin);
            }
            if (!process.waitFor(timeout.toMillis(), TimeUnit.MILLISECONDS)) {
                process.destroyForcibly();
                process.waitFor(10, TimeUnit.SECONDS);
                throw new RenderExecutionException("render_tool_timeout", true);
            }
            byte[] output = stdout.get();
            byte[] diagnostics = stderr.get();
            if (output.length > MAX_CAPTURE_BYTES || diagnostics.length > MAX_CAPTURE_BYTES) {
                throw new RenderExecutionException("render_tool_output_limit_exceeded", false);
            }
            if (process.exitValue() != 0) {
                String diagnostic = new String(diagnostics, StandardCharsets.UTF_8);
                String category = diagnostic.toLowerCase().contains("unknown")
                        || diagnostic.toLowerCase().contains("parse")
                        ? "render_source_rejected"
                        : "render_tool_failed";
                throw new RenderExecutionException(category, !category.equals("render_source_rejected"));
            }
            return new ToolResult(output, new String(diagnostics, StandardCharsets.UTF_8));
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            process.destroyForcibly();
            throw new RenderExecutionException("render_interrupted", true, exception);
        } catch (RenderExecutionException exception) {
            process.destroyForcibly();
            throw exception;
        } catch (Exception exception) {
            process.destroyForcibly();
            throw new RenderExecutionException("render_tool_io_failed", true, exception);
        }
    }

    record ToolResult(byte[] stdout, String stderr) {
    }
}
