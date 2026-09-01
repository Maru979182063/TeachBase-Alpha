/**
 * Owns explicit human review cases and append-only decisions. Question content is
 * never edited here; the module can only publish a frozen revision through the
 * Questions public review gateway.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Review",
        allowedDependencies = {"identity::api", "question::api", "audit::api"})
package com.teachbase.server.review;
