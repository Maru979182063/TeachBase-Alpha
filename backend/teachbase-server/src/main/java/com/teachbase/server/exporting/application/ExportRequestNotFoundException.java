package com.teachbase.server.exporting.application;

/** Workspace-scoped export request was not found. */
public class ExportRequestNotFoundException extends RuntimeException {

    public ExportRequestNotFoundException() {
        super("export_request_not_found");
    }
}
