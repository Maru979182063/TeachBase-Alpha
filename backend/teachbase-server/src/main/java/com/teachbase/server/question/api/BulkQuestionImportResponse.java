package com.teachbase.server.question.api;

import java.util.List;

/** Ordered import outcomes corresponding one-for-one with the request batch. */
public record BulkQuestionImportResponse(List<QuestionImportResult> results) {
}
