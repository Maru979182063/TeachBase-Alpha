/**
 * Owns versioned knowledge-point trees, aliases, and assignments to immutable
 * question revisions. Difficulty policy is intentionally outside this module.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Taxonomy",
        allowedDependencies = {"identity::api", "question::api", "audit::api"})
package com.teachbase.server.taxonomy;
