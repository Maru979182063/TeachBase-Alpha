package com.teachbase.server.fileasset.application;

import java.util.Optional;
import java.util.UUID;

/** Persistence port enforcing workspace-local checksum idempotency. */
public interface FileAssetRepository {

    Optional<FileRegistration> findByWorkspaceAndSha256(UUID workspaceId, String sha256);

    FileRegistration insert(RegisterFileCommand command);
}
