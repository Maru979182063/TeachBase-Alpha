package com.teachbase.server.audit.api;

/** Application port for recording an append-only business event in the caller's transaction. */
public interface AuditTrail {

    void record(AuditCommand command);
}
