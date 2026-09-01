package com.teachbase.server.fileasset.api;

import com.teachbase.server.fileasset.application.FileRegistration;
import java.util.UUID;

/** Registered logical file and immutable version identity returned to clients. */
public record FileRegistrationResponse(
        UUID fileAssetId,
        UUID fileVersionId,
        UUID workspaceId,
        String originalFilename,
        String storageProvider,
        String storageKey,
        String mediaType,
        long sizeBytes,
        String sha256,
        boolean created) {

    static FileRegistrationResponse from(FileRegistration registration) {
        return new FileRegistrationResponse(
                registration.fileAssetId(),
                registration.fileVersionId(),
                registration.workspaceId(),
                registration.originalFilename(),
                registration.storageProvider(),
                registration.storageKey(),
                registration.mediaType(),
                registration.sizeBytes(),
                registration.sha256(),
                registration.created());
    }
}
