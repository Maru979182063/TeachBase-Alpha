package com.teachbase.server.releaseseed.application;

import java.util.UUID;

/** Imported question identity and review case persisted at one checkpoint. */
public record ReleaseSeedItemResult(
        UUID questionId,
        UUID questionRevisionId,
        UUID reviewCaseId,
        boolean createdQuestion,
        boolean createdRevision) {
}
