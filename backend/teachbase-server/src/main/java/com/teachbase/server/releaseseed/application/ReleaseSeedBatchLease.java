package com.teachbase.server.releaseseed.application;

import java.util.UUID;

/** Exclusive import lease and durable resume cursor for one package digest. */
public record ReleaseSeedBatchLease(
        UUID releaseSeedBatchId,
        UUID workerToken,
        String status,
        int nextQuestionIndex,
        int attemptNo,
        int questionCount,
        int importedCount,
        int reusedCount,
        int approvedCount) {

    public boolean completed() {
        return status.equals("completed");
    }
}
