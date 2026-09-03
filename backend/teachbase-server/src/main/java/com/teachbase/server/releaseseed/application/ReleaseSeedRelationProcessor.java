package com.teachbase.server.releaseseed.application;

import com.teachbase.server.question.api.QuestionIngestionLinker;
import com.teachbase.server.question.api.QuestionRelationCommand;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * 中文维护说明：本文件属于首发数据包导入模块的业务规则与事务编排层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Resolves package external keys and writes all graph edges in one retryable transaction.
 */
@Service
public class ReleaseSeedRelationProcessor {

    private final ReleaseSeedRepository checkpoints;
    private final QuestionIngestionLinker links;

    public ReleaseSeedRelationProcessor(ReleaseSeedRepository checkpoints, QuestionIngestionLinker links) {
        this.checkpoints = checkpoints;
        this.links = links;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void process(
            ReleaseSeedBatchLease lease,
            ValidatedReleaseSeedPackage seedPackage,
            ReleaseSeedProperties properties) {
        checkpoints.heartbeat(lease.releaseSeedBatchId(), lease.workerToken(), properties.effectiveLeaseDuration());
        int count = 0;
        for (var relation : seedPackage.relations()) {
            var from = checkpoints.findQuestionId(
                            lease.releaseSeedBatchId(), relation.path("fromExternalKey").asText())
                    .orElseThrow(() -> new ReleaseSeedValidationException("release_seed_relation_parent_missing"));
            var to = checkpoints.findQuestionId(
                            lease.releaseSeedBatchId(), relation.path("toExternalKey").asText())
                    .orElseThrow(() -> new ReleaseSeedValidationException("release_seed_relation_child_missing"));
            links.linkRelation(new QuestionRelationCommand(
                    properties.workspaceId(), from, to, relation.path("relationType").asText(),
                    relation.path("ordinal").asInt(0)));
            count++;
        }
        checkpoints.recordRelations(
                lease.releaseSeedBatchId(), lease.workerToken(), count, properties.effectiveLeaseDuration());
    }
}
