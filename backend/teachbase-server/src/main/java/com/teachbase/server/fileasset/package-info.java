/** Owns portable file identities, immutable byte versions, hashes, and storage keys. */
@org.springframework.modulith.ApplicationModule(
        displayName = "File Assets",
        allowedDependencies = {"identity::api", "audit::api"})
package com.teachbase.server.fileasset;
