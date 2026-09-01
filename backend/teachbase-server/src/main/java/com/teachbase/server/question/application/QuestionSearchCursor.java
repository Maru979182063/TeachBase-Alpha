package com.teachbase.server.question.application;

import java.time.OffsetDateTime;
import java.util.UUID;

/** Decoded keyset cursor matching revision-created-desc/question-id-asc ordering. */
public record QuestionSearchCursor(OffsetDateTime revisionCreatedAt, UUID questionId) {
}
