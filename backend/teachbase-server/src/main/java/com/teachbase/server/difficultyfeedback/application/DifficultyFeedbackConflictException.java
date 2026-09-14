package com.teachbase.server.difficultyfeedback.application;

import java.util.UUID;

/** 中文维护说明：封装幂等或 CAS 冲突，并在可用时返回最新状态。 */
public class DifficultyFeedbackConflictException extends RuntimeException {
    private final Long currentStateVersion;
    private final UUID currentSnapshotId;
    private final String status;

    public DifficultyFeedbackConflictException(String code) {
        this(code, null, null, null);
    }

    public DifficultyFeedbackConflictException(
            String code, Long currentStateVersion, UUID currentSnapshotId, String status) {
        super(code);
        this.currentStateVersion = currentStateVersion;
        this.currentSnapshotId = currentSnapshotId;
        this.status = status;
    }

    public Long currentStateVersion() {
        return currentStateVersion;
    }

    public UUID currentSnapshotId() {
        return currentSnapshotId;
    }

    public String status() {
        return status;
    }
}
