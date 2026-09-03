package com.teachbase.server.question.application;

import com.teachbase.server.question.api.QuestionImportResult;
import com.teachbase.server.question.api.QuestionSearchItem;
import java.util.List;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于题目、修订与检索模块的业务规则与事务编排层，定义持久化端口，调用方只依赖业务所需的最小能力。
 *
 * 英文术语对照：Persistence port for atomic revision import and approved-question search.
 */
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
