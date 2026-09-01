package com.teachbase.server.identity.api;

/** Actor is not an active member of the workspace being mutated. */
public class ActorNotWorkspaceMemberException extends RuntimeException {

    public ActorNotWorkspaceMemberException() {
        super("actor_not_active_workspace_member");
    }
}
