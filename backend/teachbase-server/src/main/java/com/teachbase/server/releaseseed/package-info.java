/**
 * Orchestrates validated Release Seed packages through public domain-module ports.
 * It owns checkpoints only and never writes question, review, taxonomy, file, or
 * source tables directly.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Release Seed",
        allowedDependencies = {
            "identity::api", "audit::api", "fileasset::api", "source::api",
            "question::api", "review::api", "taxonomy::api"
        })
package com.teachbase.server.releaseseed;
