package com.teachbase.server.collection.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.question.api.QuestionRevisionDescriptor;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，定义持久化端口，调用方只依赖业务所需的最小能力。
 *
 * 英文术语对照：Persistence port for versioned collection drafts, checkpoints, and snapshots.
 */
public interface CollectionRepository {

    CollectionDraft create(UUID workspaceId, UUID actorUserId, String name);

    Optional<CollectionDraft> find(UUID collectionId, UUID workspaceId);

    List<CollectionCheckpoint> listCheckpoints(UUID collectionId, UUID workspaceId, int limit);

    Optional<CollectionCheckpoint> findCheckpoint(UUID collectionId, UUID checkpointId, UUID workspaceId);

    CollectionDraft save(
            UUID collectionId,
            UUID workspaceId,
            UUID actorUserId,
            long expectedVersion,
            String checkpointKind,
            List<QuestionRevisionDescriptor> revisions,
            List<JsonNode> settings);

    CollectionSnapshot snapshot(
            UUID collectionId,
            UUID workspaceId,
            UUID actorUserId,
            long expectedVersion,
            List<QuestionRevisionDescriptor> expectedRevisions);
}
