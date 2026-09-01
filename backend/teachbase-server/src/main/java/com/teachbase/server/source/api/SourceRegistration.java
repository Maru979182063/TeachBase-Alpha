package com.teachbase.server.source.api;

import java.util.UUID;

/** Stable source aggregate identity and idempotency outcome. */
public record SourceRegistration(UUID id, boolean created) {
}
