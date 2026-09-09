package com.teachbase.server.canonicalimport.application;

import java.time.Duration;
import java.util.List;
import java.util.UUID;

/** 中文维护说明：G5 ledger 持久化端口；领域资产仍由各模块自己的公开端口写入。 */
public interface CanonicalImportRepository {

    ValidationSaveResult saveValidation(UUID workspaceId, UUID actorUserId, CanonicalImportPlan plan);

    ImportRequestRecord requireRequest(UUID importRequestId, UUID workspaceId);

    List<ImportOperationRecord> operations(UUID importRequestId, UUID workspaceId);

    ImportRequestRecord acquire(UUID importRequestId, UUID workspaceId, UUID workerToken, Duration leaseDuration);

    void markRunning(UUID importRequestId, UUID workerToken, UUID importOperationId, Duration leaseDuration);

    void complete(UUID importOperationId, ImportOperationOutcome outcome);

    void fail(UUID importRequestId, UUID importOperationId, String code, String detail);

    void completeRequest(UUID importRequestId, UUID workerToken, String resultFingerprint);

    void assertCompletedTargetsExist(UUID importRequestId, UUID workspaceId);

    record ValidationSaveResult(ImportRequestRecord request, boolean replayed) {
    }
}
