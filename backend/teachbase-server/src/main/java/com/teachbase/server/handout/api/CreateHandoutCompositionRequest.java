package com.teachbase.server.handout.api;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import java.util.List;
import java.util.UUID;

/** 中文维护说明：一次事务写入某个精确 editor revision 的完整 edition composition。 */
public record CreateHandoutCompositionRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotEmpty List<@Valid HandoutEditionInput> editions,
        @NotNull List<@Valid EditorRevisionArtifactInput> artifacts) {
}
