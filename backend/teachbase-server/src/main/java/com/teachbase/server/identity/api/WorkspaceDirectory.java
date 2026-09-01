package com.teachbase.server.identity.api;

import java.util.UUID;

/** Minimal tenant authorization lookup shared without exposing identity persistence. */
public interface WorkspaceDirectory {

    boolean exists(UUID workspaceId);

    boolean isActiveMember(UUID workspaceId, UUID userId);
}
