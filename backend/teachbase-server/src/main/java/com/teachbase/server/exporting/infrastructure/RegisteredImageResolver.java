package com.teachbase.server.exporting.infrastructure;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.teachbase.server.fileasset.api.StoredFileDirectory;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Base64;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Component;

/**
 * 中文维护说明：只解析同租户已登记的图片，将核对过的字节复制到本次渲染目录。
 * 未解析图片、越界路径、符号链接逃逸或哈希不符必须阻断，不能让 Pandoc 静默丢图。
 */
@Component
class RegisteredImageResolver {
    private final StoredFileDirectory files;

    RegisteredImageResolver(StoredFileDirectory files) {
        this.files = files;
    }

    void resolve(JsonNode ast, UUID workspaceId, Path storageRoot, Path workDirectory) throws IOException {
        if (ast.isObject() && "Image".equals(ast.path("t").asText())) {
            ArrayNode target = (ArrayNode) ast.path("c").get(2);
            String uri = target.get(0).asText();
            if (!uri.startsWith("tbasset:")) throw new RenderExecutionException("render_image_not_registered", false);
            String sha = uri.substring("tbasset:".length());
            if (!sha.matches("[0-9a-f]{64}")) throw new RenderExecutionException("render_image_hash_invalid", false);
            var file = files.findBySha256(workspaceId, sha)
                    .orElseThrow(() -> new RenderExecutionException("render_image_not_registered", false));
            String extension = Map.of("image/png", ".png", "image/jpeg", ".jpg").get(file.mediaType());
            if (extension == null || file.sizeBytes() > 32 * 1024 * 1024) {
                throw new RenderExecutionException("render_image_format_or_size_invalid", false);
            }
            Path source = storageRoot.resolve(file.storageKey()).normalize();
            if (!source.startsWith(storageRoot) || !source.toRealPath().startsWith(storageRoot.toRealPath())) {
                throw new RenderExecutionException("render_image_storage_escape", false);
            }
            if (Files.size(source) != file.sizeBytes()) throw new RenderExecutionException("render_image_bytes_mismatch", false);
            byte[] bytes = Files.readAllBytes(source);
            if (bytes.length != file.sizeBytes() || !sha256(bytes).equals(sha)) {
                throw new RenderExecutionException("render_image_bytes_mismatch", false);
            }
            String relative = "assets/" + sha + extension;
            Path local = workDirectory.resolve(relative);
            Files.createDirectories(local.getParent());
            Files.write(local, bytes);
            target.set(0, target.textNode(relative));
        }
        // 仅对 LaTeX Math 节点转换已知圈号命令，原题库与快照原文保持不变。
        if (ast.isObject() && "Math".equals(ast.path("t").asText())) {
            ArrayNode math = (ArrayNode) ast.path("c");
            String tex = math.get(1).asText();
            for (int n = 1; n <= 20; n++) {
                tex = tex.replace("\\textcircled{" + n + "}", "\\text{" + (char) (0x2460 + n - 1) + "}");
            }
            math.set(1, math.textNode(tex));
        }
        if (ast.isContainerNode()) for (JsonNode child : ast) resolve(child, workspaceId, storageRoot, workDirectory);
    }

    void embedForDocx(JsonNode ast, Path workDirectory) throws IOException {
        // Pandoc 沙箱不读取任意图片文件；只把前一步核验过的本次工作目录字节内嵌给 DOCX writer。
        if (ast.isObject() && "Image".equals(ast.path("t").asText())) {
            ArrayNode target = (ArrayNode) ast.path("c").get(2);
            String relative = target.get(0).asText();
            if (!relative.startsWith("assets/")) throw new RenderExecutionException("render_image_not_resolved", false);
            Path image = workDirectory.resolve(relative).normalize();
            if (!image.startsWith(workDirectory)) throw new RenderExecutionException("render_image_storage_escape", false);
            String type = relative.endsWith(".png") ? "image/png" : "image/jpeg";
            target.set(0, target.textNode("data:" + type + ";base64," + Base64.getEncoder().encodeToString(Files.readAllBytes(image))));
        }
        if (ast.isContainerNode()) for (JsonNode child : ast) embedForDocx(child, workDirectory);
    }

    private String sha256(byte[] bytes) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)); }
        catch (NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }
}
