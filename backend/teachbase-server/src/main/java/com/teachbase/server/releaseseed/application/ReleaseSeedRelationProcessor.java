package com.teachbase.server.releaseseed.application;

import com.teachbase.server.question.api.QuestionIngestionLinker;
import com.teachbase.server.question.api.QuestionRelationCommand;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/** Resolves package external keys and writes all graph edges in one retryable transaction. */
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
