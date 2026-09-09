package com.teachbase.server.canonicalimport.api;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.util.UUID;

/** 中文维护说明：Commit/Resume 必须再次绑定 validation 时的精确 package hash。 */
public record CanonicalImportActionRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotBlank String packageHash,
        String testFaultBeforeOperationKey,
        String testFaultAfterOperationKey) {
}
