package com.teachbase.server.ingestion.infrastructure;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.fileasset.api.GeneratedFileCommand;
import com.teachbase.server.fileasset.api.GeneratedFileRegistrar;
import com.teachbase.server.fileasset.api.StoredFileDirectory;
import com.teachbase.server.ingestion.application.DeliveryContract;
import com.teachbase.server.ingestion.application.DeliveryException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.channels.FileChannel;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** 中文维护说明：预检只读取；提交复制已核验字节到不可变存储，失败残留由对账报告保留。 */
@Component
public class DeliveryFiles {
    public static final int MAX_FILE_BYTES = 64 * 1024 * 1024;
    private static final long MAX_PACKAGE_BYTES = 512L * 1024 * 1024;
    private final Path root;
    private final StoredFileDirectory directory;
    private final GeneratedFileRegistrar registrar;
    public record Registered(UUID fileVersionId, String storageKey, String sha256, String mediaType, long sizeBytes) {}
    public DeliveryFiles(@Value("${teachbase.rendering.storage-root}") String root, StoredFileDirectory directory, GeneratedFileRegistrar registrar) {
        this.root = Path.of(root).toAbsolutePath().normalize(); this.directory = directory; this.registrar = registrar;
    }
    public List<DeliveryContract.Issue> inspect(JsonNode m) {
        var issues = new ArrayList<DeliveryContract.Issue>(); long total = 0;
        for (int i = 0; i < m.path("files").size(); i++) {
            var f = m.path("files").get(i); long size = f.path("sizeBytes").asLong();
            if (size > MAX_FILE_BYTES || total > MAX_PACKAGE_BYTES - size) { issues.add(new DeliveryContract.Issue("delivery_bytes_limit", "/files/" + i)); continue; }
            total += size;
            try {
                if (f.path("mediaType").asText().length() > 255) throw new DeliveryException(422, "file_media_type_too_long");
                String name = Path.of(f.path("path").asText()).getFileName().toString();
                if (name.chars().anyMatch(Character::isISOControl)) throw new DeliveryException(422, "file_name_invalid");
                checked(resolve(m, f), f);
            } catch (Exception e) { issues.add(new DeliveryContract.Issue(e instanceof DeliveryException ? e.getMessage() : "file_unavailable", "/files/" + i)); }
        }
        return issues;
    }
    private Path resolve(JsonNode m, JsonNode f) throws java.io.IOException {
        UUID workspace = UUID.fromString(m.path("workspaceId").asText());
        var stored = directory.findBySha256(workspace, f.path("sha256").asText());
        if (stored.isPresent()) {
            var s = stored.get();
            if (!s.mediaType().equals(f.path("mediaType").asText()) || s.sizeBytes() != f.path("sizeBytes").asLong()) throw new DeliveryException(422, "registered_file_metadata_mismatch");
            return contained(root, root.resolve(s.storageKey()));
        }
        Path inbox = root.resolve("inbox").resolve(workspace.toString()).resolve(m.path("packageId").asText());
        return contained(inbox, inbox.resolve(f.path("path").asText()));
    }
    private Path contained(Path boundary, Path file) throws java.io.IOException {
        Path n = file.normalize();
        if (!n.startsWith(boundary.normalize()) || !n.toRealPath().startsWith(boundary.toRealPath())
                || !n.toRealPath().startsWith(root.toRealPath())) throw new DeliveryException(422, "file_storage_escape");
        return n;
    }
    private byte[] checked(Path file, JsonNode f) throws java.io.IOException {
        if (!Files.isRegularFile(file) || Files.size(file) != f.path("sizeBytes").asLong()) throw new DeliveryException(422, "file_size_mismatch");
        byte[] bytes; try (var in = Files.newInputStream(file)) { bytes = in.readNBytes(MAX_FILE_BYTES + 1); }
        if (bytes.length > MAX_FILE_BYTES || bytes.length != f.path("sizeBytes").asLong() || !DeliveryContract.sha256(bytes).equals(f.path("sha256").asText())) throw new DeliveryException(422, "file_hash_mismatch");
        return bytes;
    }
    public Registered store(JsonNode m, JsonNode f, UUID actor) {
        try {
            byte[] bytes = checked(resolve(m, f), f);
            UUID workspace = UUID.fromString(m.path("workspaceId").asText()); String sha = f.path("sha256").asText();
            String key = directory.findBySha256(workspace,sha).map(StoredFileDirectory.StoredFile::storageKey)
                    .orElse("delivery-blobs/" + workspace + "/" + sha);
            Path target = root.resolve(key); Files.createDirectories(target.getParent());
            if (!target.getParent().toRealPath().startsWith(root.toRealPath())) throw new DeliveryException(422, "file_storage_escape");
            if (!Files.exists(target)) {
                Path temp = Files.createTempFile(target.getParent(), ".incoming-", ".tmp");
                try {
                    Files.write(temp, bytes); try (var channel = FileChannel.open(temp, StandardOpenOption.WRITE)) { channel.force(true); }
                    try { Files.move(temp, target); } catch (java.nio.file.FileAlreadyExistsException ignored) { /* 并发赢家须在下方重新验字节。 */ }
                } finally { Files.deleteIfExists(temp); }
            }
            checked(contained(root, target), f);
            var registered = registrar.registerGeneratedFile(new GeneratedFileCommand(workspace, actor,
                    Path.of(f.path("path").asText()).getFileName().toString(), key, f.path("mediaType").asText(), bytes.length, sha));
            checked(contained(root, root.resolve(registered.storageKey())), f);
            return new Registered(registered.fileVersionId(), registered.storageKey(), sha, f.path("mediaType").asText(), bytes.length);
        } catch (DeliveryException e) { throw e; } catch (Exception e) { throw new DeliveryException(422, "file_storage_failed"); }
    }
    public Path storageRoot() { return root; }
}
