package com.teachbase.server.source.api;

/** Named module port for durable source evidence registration. */
public interface SourceCatalog {

    SourceRegistration registerDocument(RegisterSourceDocumentCommand command);

    SourceRegistration registerRegion(RegisterSourceRegionCommand command);
}
