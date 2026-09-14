package com.teachbase.server.tagfeedback.application;

import java.util.UUID;

/**
 * 中文维护说明：表示幂等载荷冲突或 stateVersion 过期；附带最新状态用于前端刷新后合并。
 */
public class TagFeedbackConflictException extends RuntimeException {

    private final Long currentStateVersion;
    private final UUID currentSnapshotId;
    private final String tagStatus;

    public TagFeedbackConflictException(String code) {
        this(code, null, null, null);
    }

    public TagFeedbackConflictException(
            String code, Long currentStateVersion, UUID currentSnapshotId, String tagStatus) {
        super(code);
        this.currentStateVersion = currentStateVersion;
        this.currentSnapshotId = currentSnapshotId;
        this.tagStatus = tagStatus;
    }

    public Long currentStateVersion() {
        return currentStateVersion;
    }

    public UUID currentSnapshotId() {
        return currentSnapshotId;
    }

    public String tagStatus() {
        return tagStatus;
    }
}
