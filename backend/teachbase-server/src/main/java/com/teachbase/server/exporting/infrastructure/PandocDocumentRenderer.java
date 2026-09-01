package com.teachbase.server.exporting.infrastructure;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.teachbase.server.editor.api.EditorSnapshotDescriptor;
import com.teachbase.server.exporting.application.RenderSourceDocument;
import com.teachbase.server.exporting.application.RenderSourceException;
import com.teachbase.server.exporting.application.TiptapMarkdownAdapter;
import com.teachbase.server.exporting.application.ExportWorkItem;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import java.util.zip.ZipFile;
import jakarta.annotation.PostConstruct;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.text.PDFTextStripper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "teachbase.rendering", name = "enabled", havingValue = "true")
/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 * Deterministic document renderer: frozen editor JSON becomes Markdown, then a
 * versioned Pandoc AST, and finally DOCX or PDF. Every artifact is structurally
 * validated before an atomic same-directory replacement makes it visible.
 */
class PandocDocumentRenderer {

    private static final String PANDOC_INPUT_FORMAT =
            "markdown+tex_math_dollars+pipe_tables+task_lists+fenced_divs+bracketed_spans";
    private final RenderingProperties properties;
    private final TiptapMarkdownAdapter adapter;
    private final ObjectMapper objectMapper;
    private final ExternalToolRunner tools = new ExternalToolRunner();

    PandocDocumentRenderer(RenderingProperties properties, TiptapMarkdownAdapter adapter, ObjectMapper objectMapper) {
        this.properties = properties;
        this.adapter = adapter;
        this.objectMapper = objectMapper;
    }

    @PostConstruct
    void verifyToolchain() {
        Path workingDirectory = Path.of(".").toAbsolutePath().normalize();
        String pandocVersion = toolVersion(properties.pandocPath(), workingDirectory);
        String typstVersion = toolVersion(properties.typstPath(), workingDirectory);
        if (pandocVersion.equals("unknown") || typstVersion.equals("unknown")) {
            throw new IllegalStateException("document_renderer_toolchain_version_unreadable");
        }
    }

    RenderedArtifact render(ExportWorkItem job, EditorSnapshotDescriptor snapshot) {
        Path storageRoot = properties.storageRoot().toAbsolutePath().normalize();
        String extension = extension(job.format());
        String storageKey = "exports/" + job.workspaceId() + "/" + job.exportRequestId() + "." + extension;
        Path target = storageRoot.resolve(storageKey).normalize();
        if (!target.startsWith(storageRoot)) throw new RenderExecutionException("render_storage_key_invalid", false);
        Path temporaryOutput = null;
        Path workDirectory = null;
        try {
            Files.createDirectories(target.getParent());
            // 同目录唯一临时文件保证并发渲染互不覆盖，并让最终移动始终位于
            // 同一文件系统，这是原子替换能够成立的前提。
            temporaryOutput = Files.createTempFile(
                    target.getParent(), "." + job.exportRequestId() + "-", ".tmp." + extension);
            workDirectory = Files.createTempDirectory(target.getParent(), ".render-work-");
            RenderSourceDocument source = adapter.adapt(snapshot.frozenContent());
            // 除最终字节外，还要持久化规范化 AST 信封及其哈希，
            // 这样渲染回归才能复现并接受审计。
            JsonNode pandocAst = parsePandocAst(source, workDirectory);
            ObjectNode envelope = objectMapper.createObjectNode();
            envelope.put("schemaVersion", 1);
            envelope.put("adapterVersion", source.adapterVersion());
            envelope.put("audience", source.audience());
            envelope.set("pandocAst", pandocAst);
            String sourceHash = sha256(canonicalBytes(envelope));
            Path astPath = workDirectory.resolve("document.pandoc.json");
            Files.write(astPath, objectMapper.writeValueAsBytes(pandocAst));
            String rendererVersion = switch (job.format()) {
                case "docx" -> renderDocx(astPath, temporaryOutput, workDirectory);
                case "pdf" -> renderPdf(astPath, temporaryOutput, workDirectory);
                default -> throw new RenderExecutionException("unsupported_render_format", false);
            };
            validateArtifact(temporaryOutput, job.format());
            atomicReplace(temporaryOutput, target);
            temporaryOutput = null;
            return new RenderedArtifact(
                    target,
                    storageKey,
                    "teachbase-export-" + job.exportRequestId() + "." + extension,
                    mediaType(job.format()),
                    Files.size(target),
                    sha256(target),
                    rendererVersion,
                    envelope,
                    sourceHash);
        } catch (RenderSourceException exception) {
            throw new RenderExecutionException(normalizeCode(exception.getMessage()), false, exception);
        } catch (RenderExecutionException exception) {
            throw exception;
        } catch (IOException exception) {
            throw new RenderExecutionException("render_artifact_io_failed", true, exception);
        } finally {
            deleteQuietly(temporaryOutput);
            deleteTreeQuietly(workDirectory);
        }
    }

    String renderHtmlForVerification(EditorSnapshotDescriptor snapshot, Path workingDirectory) {
        RenderSourceDocument source = adapter.adapt(snapshot.frozenContent());
        JsonNode ast = parsePandocAst(source, workingDirectory);
        try {
            byte[] astBytes = objectMapper.writeValueAsBytes(ast);
            var result = tools.run(List.of(
                    properties.pandocPath(), "--from=json", "--to=html5", "--mathml", "--wrap=none"),
                    workingDirectory, astBytes, properties.processTimeout());
            return new String(result.stdout(), StandardCharsets.UTF_8);
        } catch (JsonProcessingException exception) {
            throw new RenderExecutionException("render_ast_not_serializable", false, exception);
        }
    }

    private JsonNode parsePandocAst(RenderSourceDocument source, Path workingDirectory) {
        var result = tools.run(List.of(
                properties.pandocPath(),
                "--sandbox",
                "--from=" + PANDOC_INPUT_FORMAT,
                "--to=json",
                "--wrap=none"),
                workingDirectory,
                source.markdown().getBytes(StandardCharsets.UTF_8),
                properties.processTimeout());
        try {
            JsonNode ast = objectMapper.readTree(result.stdout());
            if (!ast.isObject() || !ast.path("pandoc-api-version").isArray() || !ast.path("blocks").isArray()) {
                throw new RenderExecutionException("render_ast_invalid", false);
            }
            return ast;
        } catch (IOException exception) {
            throw new RenderExecutionException("render_ast_invalid", false, exception);
        }
    }

    private String renderDocx(Path astPath, Path output, Path workingDirectory) {
        tools.run(List.of(
                properties.pandocPath(),
                "--sandbox",
                "--from=json",
                "--to=docx",
                "--output=" + output,
                astPath.toString()),
                workingDirectory, null, properties.processTimeout());
        return "pandoc/" + toolVersion(properties.pandocPath(), workingDirectory) + ";adapter/1";
    }

    private String renderPdf(Path astPath, Path output, Path workingDirectory) {
        Path typstSource = workingDirectory.resolve("document.typ");
        tools.run(List.of(
                properties.pandocPath(),
                "--sandbox",
                "--from=json",
                "--to=typst",
                "--output=" + typstSource,
                astPath.toString()),
                workingDirectory, null, properties.processTimeout());
        tools.run(List.of(
                properties.typstPath(),
                "compile",
                "--root", workingDirectory.toString(),
                typstSource.toString(),
                output.toString()),
                workingDirectory, null, properties.processTimeout());
        return "pandoc/" + toolVersion(properties.pandocPath(), workingDirectory)
                + ";typst/" + toolVersion(properties.typstPath(), workingDirectory) + ";adapter/1";
    }

    private String toolVersion(String executable, Path workingDirectory) {
        var result = tools.run(List.of(executable, "--version"), workingDirectory, null, properties.processTimeout());
        String firstLine = new String(result.stdout(), StandardCharsets.UTF_8).lines().findFirst().orElse("unknown");
        var matcher = java.util.regex.Pattern.compile("\\d+\\.\\d+(?:\\.\\d+)?(?:[-+][A-Za-z0-9.-]+)?")
                .matcher(firstLine);
        return matcher.find() ? normalizeVersion(matcher.group()) : "unknown";
    }

    private void validateArtifact(Path path, String format) throws IOException {
        if (!Files.isRegularFile(path) || Files.size(path) < 100) {
            throw new RenderExecutionException("render_artifact_empty", true);
        }
        if (format.equals("pdf")) {
            try (InputStream input = Files.newInputStream(path)) {
                byte[] header = input.readNBytes(5);
                if (!new String(header, StandardCharsets.US_ASCII).equals("%PDF-")) {
                    throw new RenderExecutionException("render_pdf_signature_invalid", false);
                }
            }
            try (var document = Loader.loadPDF(path.toFile())) {
                if (document.getNumberOfPages() < 1) {
                    throw new RenderExecutionException("render_pdf_has_no_pages", false);
                }
                String text = new PDFTextStripper().getText(document);
                if (text == null || text.isBlank()) {
                    throw new RenderExecutionException("render_pdf_text_not_extractable", false);
                }
            }
            return;
        }
        try (ZipFile zip = new ZipFile(path.toFile())) {
            if (zip.getEntry("[Content_Types].xml") == null || zip.getEntry("word/document.xml") == null) {
                throw new RenderExecutionException("render_docx_structure_invalid", false);
            }
        }
    }

    private void atomicReplace(Path source, Path target) throws IOException {
        // 不提供非原子降级路径：明确拒绝不支持合同的文件系统，
        // 比向用户暴露只复制了一部分的文档更安全。
        try {
            Files.move(source, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } catch (AtomicMoveNotSupportedException exception) {
            throw new RenderExecutionException("atomic_replace_not_supported", false, exception);
        }
    }

    private byte[] canonicalBytes(JsonNode node) throws JsonProcessingException {
        return objectMapper.writer().with(com.fasterxml.jackson.databind.SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS)
                .writeValueAsBytes(node);
    }

    private String sha256(Path path) throws IOException {
        try (InputStream input = Files.newInputStream(path)) {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] buffer = new byte[64 * 1024];
            int read;
            while ((read = input.read(buffer)) >= 0) digest.update(buffer, 0, read);
            return HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("sha256_unavailable", exception);
        }
    }

    private String sha256(byte[] content) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("sha256_unavailable", exception);
        }
    }

    private String extension(String format) {
        return switch (format) {
            case "docx" -> "docx";
            case "pdf" -> "pdf";
            default -> throw new RenderExecutionException("unsupported_render_format", false);
        };
    }

    private String mediaType(String format) {
        return format.equals("docx")
                ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                : "application/pdf";
    }

    private String normalizeCode(String message) {
        if (message == null || message.isBlank()) return "render_source_invalid";
        int separator = message.indexOf(':');
        String code = separator >= 0 ? message.substring(0, separator) : message;
        return code.matches("[a-z0-9_]+") ? code : "render_source_invalid";
    }

    private String normalizeVersion(String value) {
        String normalized = value.replaceAll("[^A-Za-z0-9._-]", "");
        return normalized.isBlank() ? "unknown" : normalized;
    }

    private void deleteQuietly(Path path) {
        if (path == null) return;
        try {
            Files.deleteIfExists(path);
        } catch (IOException ignored) {
            // worker 负责记录主失败；临时文件清扫 gate 会再次尝试清理。
        }
    }

    private void deleteTreeQuietly(Path root) {
        if (root == null || !Files.exists(root)) return;
        try (var paths = Files.walk(root)) {
            paths.sorted(java.util.Comparator.reverseOrder()).forEach(this::deleteQuietly);
        } catch (IOException ignored) {
            // worker 负责记录主失败；临时文件清扫 gate 会再次尝试清理。
        }
    }
}
