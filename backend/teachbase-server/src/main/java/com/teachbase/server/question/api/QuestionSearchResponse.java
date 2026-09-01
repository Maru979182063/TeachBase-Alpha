package com.teachbase.server.question.api;

import java.util.List;

/** Bounded keyset page; the opaque cursor is null when no later page exists. */
public record QuestionSearchResponse(List<QuestionSearchItem> items, int limit, String nextCursor) {
}
