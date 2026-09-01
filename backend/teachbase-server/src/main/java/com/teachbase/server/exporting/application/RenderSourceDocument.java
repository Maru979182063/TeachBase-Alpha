package com.teachbase.server.exporting.application;

/** Deterministic audience-specific Markdown produced from a frozen editor snapshot. */
public record RenderSourceDocument(
        int schemaVersion,
        String adapterVersion,
        String audience,
        String markdown) {
}
