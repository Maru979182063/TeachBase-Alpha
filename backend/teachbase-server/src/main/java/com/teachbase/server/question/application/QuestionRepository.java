package com.teachbase.server.question.application;

import com.teachbase.server.question.api.QuestionImportResult;
import com.teachbase.server.question.api.QuestionSearchItem;
import java.util.List;
import java.util.UUID;

/** Persistence port for atomic revision import and approved-question search. */
public interface QuestionRepository {

    QuestionImportResult importRevision(NormalizedQuestionRevision revision);

    List<QuestionSearchItem> search(
            UUID workspaceId,
            String reviewStatus,
            String query,
            String subject,
            String stage,
            String grade,
            String questionType,
            Integer difficultyStars,
            QuestionSearchCursor cursor,
            int fetchLimit);
}
