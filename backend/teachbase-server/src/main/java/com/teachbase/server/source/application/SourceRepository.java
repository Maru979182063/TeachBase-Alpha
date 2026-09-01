package com.teachbase.server.source.application;

import com.teachbase.server.source.api.RegisterSourceDocumentCommand;
import com.teachbase.server.source.api.RegisterSourceRegionCommand;
import com.teachbase.server.source.api.SourceRegistration;

/** Persistence port for workspace-scoped, idempotent source evidence. */
public interface SourceRepository {

    SourceRegistration registerDocument(RegisterSourceDocumentCommand command);

    SourceRegistration registerRegion(RegisterSourceRegionCommand command);
}
