/**
 * Owns question baskets, optimistic draft saves, recoverable checkpoints, and
 * immutable publication snapshots. It pins concrete question revisions through the
 * question module's public API.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Question Collections",
        allowedDependencies = {"identity::api", "question::api", "audit::api"})
package com.teachbase.server.collection;
