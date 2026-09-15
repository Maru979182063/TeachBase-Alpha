package com.teachbase.server.governanceprojection.application;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;

/** 中文维护说明：投影 hash 排除 projected_at，只覆盖可由 authority 重建的稳定语义。 */
public final class GovernanceProjectionHasher {

    private GovernanceProjectionHasher() {
    }

    public static String tagHash(TagAuthority value) {
        return sha256(String.join("|",
                "TAG", value.workspaceId().toString(), value.questionRevisionId().toString(),
                value.taxonomyKey(), value.taxonomyVersionId().toString(), value.currentSnapshotId().toString(),
                nullable(value.primaryNodeId()), join(value.secondaryNodeIds()), value.decisionSource(),
                value.status(), Long.toString(value.stateVersion()), value.labelSetHash()));
    }

    public static String difficultyHash(DifficultyAuthority value) {
        return sha256(String.join("|",
                "DIFFICULTY", value.workspaceId().toString(), value.questionRevisionId().toString(),
                value.rubricKey(), value.rubricVersionId().toString(), value.contextKey(), value.contextHash(),
                value.currentSnapshotId().toString(), nullable(value.difficultyValue()), value.decisionSource(),
                value.status(), Long.toString(value.stateVersion())));
    }

    public static UUID stableProjectionId(String domain, UUID workspaceId, UUID questionRevisionId, String dimension) {
        String key = domain + "|" + workspaceId + "|" + questionRevisionId + "|" + dimension;
        return UUID.nameUUIDFromBytes(key.getBytes(StandardCharsets.UTF_8));
    }

    private static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("sha256_unavailable", exception);
        }
    }

    private static String join(List<UUID> values) {
        return values.stream().map(UUID::toString).reduce((left, right) -> left + "," + right).orElse("");
    }

    private static String nullable(Object value) {
        return value == null ? "" : value.toString();
    }

    public record TagAuthority(
            UUID stateId, UUID workspaceId, UUID questionId, UUID questionRevisionId,
            String taxonomyKey, UUID taxonomyVersionId, UUID currentSnapshotId,
            UUID primaryNodeId, List<UUID> secondaryNodeIds, String decisionSource,
            String status, long stateVersion, String labelSetHash) {
    }

    public record DifficultyAuthority(
            UUID stateId, UUID workspaceId, UUID questionId, UUID questionRevisionId,
            String rubricKey, UUID rubricVersionId, String contextKey, String contextHash,
            UUID currentSnapshotId, Integer difficultyValue, String decisionSource,
            String status, long stateVersion) {
    }
}
