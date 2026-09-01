package com.teachbase.server.fileasset.api;

import java.util.UUID;

/** Minimal cross-module result for a registered generated artifact. */
public record GeneratedFileRegistration(
        UUID fileVersionId,
        String storageKey,
        boolean created) {
}
