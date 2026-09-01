package com.teachbase.server.identity.api;

/** Requested workspace does not exist. */
public class WorkspaceNotFoundException extends RuntimeException {

    public WorkspaceNotFoundException() {
        super("workspace_not_found");
    }
}
