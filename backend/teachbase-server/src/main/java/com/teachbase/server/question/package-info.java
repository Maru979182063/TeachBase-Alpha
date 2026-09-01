/**
 * Owns stable question identities, immutable content revisions, review visibility,
 * provenance, and indexed retrieval. Collections and editors consume only its public
 * revision directory so they cannot couple to question persistence internals.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Questions",
        allowedDependencies = {"identity::api", "audit::api"})
package com.teachbase.server.question;
