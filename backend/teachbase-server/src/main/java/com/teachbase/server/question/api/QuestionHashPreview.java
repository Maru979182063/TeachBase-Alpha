package com.teachbase.server.question.api;

/** Canonical server-computed hashes for a normalized question import item. */
public record QuestionHashPreview(
        String contentHash,
        String sourcePayloadHash,
        String importEnvelopeHash) {
}
