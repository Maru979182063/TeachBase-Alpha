/**
 * Owns canonical editor documents, immutable revisions, audience projection, and
 * export-ready snapshots. Browser interaction and visual layout remain frontend concerns.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Editor Content",
        allowedDependencies = {"identity::api", "question::api", "audit::api"})
package com.teachbase.server.editor;
