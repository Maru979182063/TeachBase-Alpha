package com.teachbase.server.releaseseed.application;

/** Test-only controlled interruption after a durable checkpoint. */
public class ReleaseSeedInjectedInterruptionException extends RuntimeException {

    public ReleaseSeedInjectedInterruptionException() {
        super("release_seed_injected_interruption");
    }
}
