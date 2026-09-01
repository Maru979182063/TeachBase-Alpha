package com.teachbase.server.exporting.application;

import java.util.Optional;
import java.util.UUID;

/** Admission and status-query port separate from worker execution transitions. */
public interface ExportRequestRepository {

    ExportRequestState create(CreateExportCommand command);

    Optional<ExportRequestState> findByIdempotencyKey(UUID workspaceId, String idempotencyKey);

    Optional<ExportRequestDetails> findById(UUID workspaceId, UUID exportRequestId);

    boolean exists(UUID workspaceId, UUID exportRequestId);
}
