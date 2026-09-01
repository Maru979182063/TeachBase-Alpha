package com.teachbase.server.review.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.OffsetDateTime;
import java.util.Optional;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，定义持久化端口，调用方只依赖业务所需的最小能力。
 *
 * 英文术语对照：Persistence port for idempotent case opening and serialized decisions.
 */
public interface ReviewRepository {

    ReviewCaseRecord open(
            UUID workspaceId,
            UUID questionId,
            UUID questionRevisionId,
            String expectedContentHash,
            UUID assignedTo,
            UUID openedBy);

    Optional<ReviewCaseRecord> lockOpen(UUID workspaceId, UUID reviewCaseId);

    ReviewCaseRecord complete(
            ReviewCaseRecord reviewCase,
            UUID actorUserId,
            String decision,
            String note,
            String policyVersion,
            String decisionSource,
            JsonNode evidence,
            OffsetDateTime evidenceOccurredAt);
}
