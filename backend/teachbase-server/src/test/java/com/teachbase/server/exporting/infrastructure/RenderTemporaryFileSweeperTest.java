package com.teachbase.server.exporting.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class RenderTemporaryFileSweeperTest {

    @TempDir
    Path temporaryRoot;

    @Test
    void removesOnlyStaleRendererTemporaryArtifacts() throws Exception {
        Path outputDirectory = Files.createDirectories(temporaryRoot.resolve("exports/workspace"));
        Path staleFile = Files.writeString(outputDirectory.resolve(".request.tmp.pdf"), "partial");
        Path freshFile = Files.writeString(outputDirectory.resolve(".fresh.tmp.docx"), "active");
        Path completedFile = Files.writeString(outputDirectory.resolve("request.pdf"), "complete");
        Path staleDirectory = Files.createDirectory(outputDirectory.resolve(".render-work-stale"));
        Path staleNested = Files.writeString(staleDirectory.resolve("document.typ"), "partial");
        FileTime old = FileTime.from(Instant.now().minusSeconds(30));
        Files.setLastModifiedTime(staleFile, old);
        Files.setLastModifiedTime(staleNested, old);
        Files.setLastModifiedTime(staleDirectory, old);
        Files.setLastModifiedTime(completedFile, old);

        var properties = new RenderingProperties(
                true, "test-worker", "pandoc", "typst", temporaryRoot,
                Duration.ofMillis(100), Duration.ofSeconds(2), Duration.ofSeconds(2));
        new RenderTemporaryFileSweeper(properties).sweep();

        assertThat(staleFile).doesNotExist();
        assertThat(staleDirectory).doesNotExist();
        assertThat(freshFile).exists();
        assertThat(completedFile).exists();
    }
}
