package com.teachbase.server.exporting.infrastructure;

import com.fasterxml.jackson.databind.JsonNode;
import java.nio.file.Path;

/** Validated local artifact and reproducible source metadata awaiting registration. */
record RenderedArtifact(
        Path path,
        String storageKey,
        String originalFilename,
        String mediaType,
        long sizeBytes,
        String sha256,
        String rendererVersion,
        JsonNode renderSourceEnvelope,
        String renderSourceHash) {
}
