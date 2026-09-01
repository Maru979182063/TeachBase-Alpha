/**
 * Converts frozen editor snapshots into durable files through a leased PostgreSQL
 * work queue. It never reads mutable editor drafts during rendering.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Exports",
        allowedDependencies = {"identity::api", "editor::api", "fileasset::api", "audit::api"})
package com.teachbase.server.exporting;
