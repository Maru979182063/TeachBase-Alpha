package com.teachbase.server.releaseseed.application;

import com.teachbase.server.fileasset.api.GeneratedFileCommand;
import com.teachbase.server.fileasset.api.GeneratedFileRegistrar;
import com.teachbase.server.fileasset.api.GeneratedFileRegistration;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.UUID;
import org.springframework.stereotype.Component;

/** Publishes validated asset bytes atomically before checksum-idempotent registration. */
@Component
public class ReleaseSeedAssetPublisher {

    private final GeneratedFileRegistrar files;

    public ReleaseSeedAssetPublisher(GeneratedFileRegistrar files) {
        this.files = files;
    }

    public GeneratedFileRegistration publish(
            UUID workspaceId,
            UUID actorUserId,
            Path packageRoot,
            Path storageRoot,
            String packageHash,
            String assetPath,
            String mediaType,
            String expectedSha256) {
        try {
            Path source = packageRoot.resolve(assetPath).normalize();
            String suffix = assetPath.substring("assets/".length());
            String storageKey = "release-seed/" + packageHash + "/" + suffix;
            Path targetRoot = storageRoot.toAbsolutePath().normalize();
            Path target = targetRoot.resolve(storageKey.replace('/', java.io.File.separatorChar)).normalize();
            if (!target.startsWith(targetRoot)) throw new ReleaseSeedValidationException("release_seed_storage_escape");
            Files.createDirectories(target.getParent());
            if (Files.exists(target)) {
                verify(target, expectedSha256);
            } else {
                Path temp = Files.createTempFile(target.getParent(), ".release-seed-", ".tmp");
                try {
                    Files.write(temp, Files.readAllBytes(source), StandardOpenOption.TRUNCATE_EXISTING);
                    verify(temp, expectedSha256);
                    Files.move(temp, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
                } finally {
                    Files.deleteIfExists(temp);
                }
            }
            return files.registerGeneratedFile(new GeneratedFileCommand(
                    workspaceId,
                    actorUserId,
                    Path.of(assetPath).getFileName().toString(),
                    storageKey,
                    mediaType == null || mediaType.isBlank() ? "application/octet-stream" : mediaType,
                    Files.size(target),
                    expectedSha256));
        } catch (IOException exception) {
            throw new ReleaseSeedValidationException("release_seed_asset_publish_failed", exception);
        }
    }

    private void verify(Path path, String expectedSha256) throws IOException {
        try {
            String actual = HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path)));
            if (!actual.equals(expectedSha256)) {
                throw new ReleaseSeedValidationException("release_seed_published_asset_hash_mismatch");
            }
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("sha256_unavailable", exception);
        }
    }
}
