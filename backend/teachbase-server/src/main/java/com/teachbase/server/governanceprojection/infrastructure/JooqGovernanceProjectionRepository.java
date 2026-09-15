package com.teachbase.server.governanceprojection.infrastructure;

import static com.teachbase.jooq.tables.GovernanceProjectionOutbox.GOVERNANCE_PROJECTION_OUTBOX;
import static com.teachbase.jooq.tables.QuestionDifficultyCurrentProjection.QUESTION_DIFFICULTY_CURRENT_PROJECTION;
import static com.teachbase.jooq.tables.QuestionDifficultySnapshot.QUESTION_DIFFICULTY_SNAPSHOT;
import static com.teachbase.jooq.tables.QuestionDifficultyState.QUESTION_DIFFICULTY_STATE;
import static com.teachbase.jooq.tables.QuestionRevision.QUESTION_REVISION;
import static com.teachbase.jooq.tables.QuestionTagCurrentProjection.QUESTION_TAG_CURRENT_PROJECTION;
import static com.teachbase.jooq.tables.QuestionTagCurrentProjectionSecondary.QUESTION_TAG_CURRENT_PROJECTION_SECONDARY;
import static com.teachbase.jooq.tables.QuestionTagSnapshot.QUESTION_TAG_SNAPSHOT;
import static com.teachbase.jooq.tables.QuestionTagSnapshotItem.QUESTION_TAG_SNAPSHOT_ITEM;
import static com.teachbase.jooq.tables.QuestionTagState.QUESTION_TAG_STATE;
import static com.teachbase.jooq.tables.WorkspaceMember.WORKSPACE_MEMBER;
import static com.teachbase.server.governanceprojection.api.GovernanceProjectionContracts.*;
import static com.teachbase.server.governanceprojection.application.GovernanceProjectionHasher.*;

import com.teachbase.server.governanceprojection.application.GovernanceProjectionRepository;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.jooq.Condition;
import org.jooq.DSLContext;
import org.jooq.Record;
import org.jooq.impl.DSL;
import org.springframework.stereotype.Repository;

/**
 * 中文维护说明：该适配器只读 authority state，并通过受保护 writer 标记维护可丢弃、可重建的投影。
 */
@Repository
public class JooqGovernanceProjectionRepository implements GovernanceProjectionRepository {

    private final DSLContext database;

    public JooqGovernanceProjectionRepository(DSLContext database) {
        this.database = database;
    }

    @Override
    public Optional<ClaimedEvent> claimNext(String workerId, OffsetDateTime now, OffsetDateTime leaseUntil) {
        Record record = database.fetchOne("""
                with candidate as (
                  select event_id
                  from teachbase_app.governance_projection_outbox
                  where ((status in ('pending','failed') and available_at <= ?::timestamptz)
                      or (status = 'processing' and lease_until <= ?::timestamptz))
                  order by created_at, event_id
                  for update skip locked
                  limit 1
                )
                update teachbase_app.governance_projection_outbox events
                set status='processing', attempt_count=attempt_count+1,
                    lease_owner=?, lease_until=?::timestamptz, processed_at=null, last_error=null
                from candidate
                where events.event_id=candidate.event_id
                returning events.*
                """, now, now, workerId, leaseUntil);
        return Optional.ofNullable(record).map(value -> event(value, workerId));
    }

    @Override
    public Optional<ClaimedEvent> lockClaim(UUID eventId, String workerId, OffsetDateTime now) {
        var value = database.selectFrom(GOVERNANCE_PROJECTION_OUTBOX)
                .where(GOVERNANCE_PROJECTION_OUTBOX.EVENT_ID.eq(eventId))
                .and(GOVERNANCE_PROJECTION_OUTBOX.STATUS.eq("processing"))
                .and(GOVERNANCE_PROJECTION_OUTBOX.LEASE_OWNER.eq(workerId))
                .and(GOVERNANCE_PROJECTION_OUTBOX.LEASE_UNTIL.gt(now))
                .forUpdate()
                .fetchOne();
        return Optional.ofNullable(value).map(record -> new ClaimedEvent(
                record.getEventId(), record.getWorkspaceId(), record.getQuestionRevisionId(),
                record.getDomain(), record.getAuthorityStateId(), record.getAuthorityStateVersion(),
                record.getEventKey(), record.getAttemptCount(), workerId));
    }

    @Override
    public Optional<TagAuthority> loadTagAuthority(UUID stateId, boolean lock) {
        var query = database.select(
                        QUESTION_TAG_STATE.STATE_ID, QUESTION_TAG_STATE.WORKSPACE_ID,
                        QUESTION_TAG_STATE.QUESTION_ID, QUESTION_TAG_STATE.QUESTION_REVISION_ID,
                        QUESTION_TAG_STATE.TAXONOMY_KEY, QUESTION_TAG_STATE.TAXONOMY_VERSION_ID,
                        QUESTION_TAG_STATE.CURRENT_SNAPSHOT_ID, QUESTION_TAG_STATE.STATUS,
                        QUESTION_TAG_STATE.STATE_VERSION, QUESTION_TAG_SNAPSHOT.SNAPSHOT_KIND,
                        QUESTION_TAG_SNAPSHOT.LABEL_SET_HASH)
                .from(QUESTION_TAG_STATE)
                .join(QUESTION_TAG_SNAPSHOT)
                .on(QUESTION_TAG_STATE.CURRENT_SNAPSHOT_ID.eq(QUESTION_TAG_SNAPSHOT.SNAPSHOT_ID))
                .where(QUESTION_TAG_STATE.STATE_ID.eq(stateId));
        Record value = lock ? query.forShare().fetchOne() : query.fetchOne();
        if (value == null) return Optional.empty();
        UUID snapshotId = value.get(QUESTION_TAG_STATE.CURRENT_SNAPSHOT_ID);
        UUID primary = database.select(QUESTION_TAG_SNAPSHOT_ITEM.TAXONOMY_NODE_ID)
                .from(QUESTION_TAG_SNAPSHOT_ITEM)
                .where(QUESTION_TAG_SNAPSHOT_ITEM.SNAPSHOT_ID.eq(snapshotId))
                .and(QUESTION_TAG_SNAPSHOT_ITEM.RELATION_TYPE.eq("primary"))
                .fetchOne(QUESTION_TAG_SNAPSHOT_ITEM.TAXONOMY_NODE_ID);
        List<UUID> secondary = database.select(QUESTION_TAG_SNAPSHOT_ITEM.TAXONOMY_NODE_ID)
                .from(QUESTION_TAG_SNAPSHOT_ITEM)
                .where(QUESTION_TAG_SNAPSHOT_ITEM.SNAPSHOT_ID.eq(snapshotId))
                .and(QUESTION_TAG_SNAPSHOT_ITEM.RELATION_TYPE.eq("secondary"))
                .orderBy(QUESTION_TAG_SNAPSHOT_ITEM.POSITION_INDEX,
                        QUESTION_TAG_SNAPSHOT_ITEM.TAXONOMY_NODE_ID)
                .fetch(QUESTION_TAG_SNAPSHOT_ITEM.TAXONOMY_NODE_ID);
        return Optional.of(new TagAuthority(
                value.get(QUESTION_TAG_STATE.STATE_ID), value.get(QUESTION_TAG_STATE.WORKSPACE_ID),
                value.get(QUESTION_TAG_STATE.QUESTION_ID), value.get(QUESTION_TAG_STATE.QUESTION_REVISION_ID),
                value.get(QUESTION_TAG_STATE.TAXONOMY_KEY), value.get(QUESTION_TAG_STATE.TAXONOMY_VERSION_ID),
                snapshotId, primary, List.copyOf(secondary), value.get(QUESTION_TAG_SNAPSHOT.SNAPSHOT_KIND),
                value.get(QUESTION_TAG_STATE.STATUS), value.get(QUESTION_TAG_STATE.STATE_VERSION),
                value.get(QUESTION_TAG_SNAPSHOT.LABEL_SET_HASH)));
    }

    @Override
    public Optional<DifficultyAuthority> loadDifficultyAuthority(UUID stateId, boolean lock) {
        var query = database.select(
                        QUESTION_DIFFICULTY_STATE.STATE_ID, QUESTION_DIFFICULTY_STATE.WORKSPACE_ID,
                        QUESTION_DIFFICULTY_STATE.QUESTION_ID, QUESTION_DIFFICULTY_STATE.QUESTION_REVISION_ID,
                        QUESTION_DIFFICULTY_STATE.RUBRIC_KEY, QUESTION_DIFFICULTY_STATE.RUBRIC_VERSION_ID,
                        QUESTION_DIFFICULTY_STATE.CONTEXT_KEY, QUESTION_DIFFICULTY_STATE.CURRENT_SNAPSHOT_ID,
                        QUESTION_DIFFICULTY_STATE.STATUS, QUESTION_DIFFICULTY_STATE.STATE_VERSION,
                        QUESTION_DIFFICULTY_SNAPSHOT.CONTEXT_HASH, QUESTION_DIFFICULTY_SNAPSHOT.DIFFICULTY_VALUE,
                        QUESTION_DIFFICULTY_SNAPSHOT.SNAPSHOT_KIND)
                .from(QUESTION_DIFFICULTY_STATE)
                .join(QUESTION_DIFFICULTY_SNAPSHOT)
                .on(QUESTION_DIFFICULTY_STATE.CURRENT_SNAPSHOT_ID.eq(QUESTION_DIFFICULTY_SNAPSHOT.SNAPSHOT_ID))
                .where(QUESTION_DIFFICULTY_STATE.STATE_ID.eq(stateId));
        Record value = lock ? query.forShare().fetchOne() : query.fetchOne();
        if (value == null) return Optional.empty();
        Short difficulty = value.get(QUESTION_DIFFICULTY_SNAPSHOT.DIFFICULTY_VALUE);
        return Optional.of(new DifficultyAuthority(
                value.get(QUESTION_DIFFICULTY_STATE.STATE_ID),
                value.get(QUESTION_DIFFICULTY_STATE.WORKSPACE_ID),
                value.get(QUESTION_DIFFICULTY_STATE.QUESTION_ID),
                value.get(QUESTION_DIFFICULTY_STATE.QUESTION_REVISION_ID),
                value.get(QUESTION_DIFFICULTY_STATE.RUBRIC_KEY),
                value.get(QUESTION_DIFFICULTY_STATE.RUBRIC_VERSION_ID),
                value.get(QUESTION_DIFFICULTY_STATE.CONTEXT_KEY),
                value.get(QUESTION_DIFFICULTY_SNAPSHOT.CONTEXT_HASH),
                value.get(QUESTION_DIFFICULTY_STATE.CURRENT_SNAPSHOT_ID),
                difficulty == null ? null : difficulty.intValue(),
                value.get(QUESTION_DIFFICULTY_SNAPSHOT.SNAPSHOT_KIND),
                value.get(QUESTION_DIFFICULTY_STATE.STATUS),
                value.get(QUESTION_DIFFICULTY_STATE.STATE_VERSION)));
    }

    @Override
    public void upsertTag(
            TagAuthority authority, UUID projectionId, String semanticHash, OffsetDateTime projectedAt) {
        enableWriter();
        int changed = database.insertInto(QUESTION_TAG_CURRENT_PROJECTION)
                .set(QUESTION_TAG_CURRENT_PROJECTION.PROJECTION_ID, projectionId)
                .set(QUESTION_TAG_CURRENT_PROJECTION.WORKSPACE_ID, authority.workspaceId())
                .set(QUESTION_TAG_CURRENT_PROJECTION.QUESTION_ID, authority.questionId())
                .set(QUESTION_TAG_CURRENT_PROJECTION.QUESTION_REVISION_ID, authority.questionRevisionId())
                .set(QUESTION_TAG_CURRENT_PROJECTION.TAXONOMY_KEY, authority.taxonomyKey())
                .set(QUESTION_TAG_CURRENT_PROJECTION.TAXONOMY_VERSION_ID, authority.taxonomyVersionId())
                .set(QUESTION_TAG_CURRENT_PROJECTION.CURRENT_SNAPSHOT_ID, authority.currentSnapshotId())
                .set(QUESTION_TAG_CURRENT_PROJECTION.PRIMARY_NODE_ID, authority.primaryNodeId())
                .set(QUESTION_TAG_CURRENT_PROJECTION.DECISION_SOURCE, authority.decisionSource())
                .set(QUESTION_TAG_CURRENT_PROJECTION.TAG_STATUS, authority.status())
                .set(QUESTION_TAG_CURRENT_PROJECTION.AUTHORITY_STATE_VERSION, authority.stateVersion())
                .set(QUESTION_TAG_CURRENT_PROJECTION.LABEL_SET_HASH, authority.labelSetHash())
                .set(QUESTION_TAG_CURRENT_PROJECTION.PROJECTION_SEMANTIC_HASH, semanticHash)
                .set(QUESTION_TAG_CURRENT_PROJECTION.PROJECTED_AT, projectedAt)
                .onConflict(QUESTION_TAG_CURRENT_PROJECTION.WORKSPACE_ID,
                        QUESTION_TAG_CURRENT_PROJECTION.QUESTION_REVISION_ID,
                        QUESTION_TAG_CURRENT_PROJECTION.TAXONOMY_KEY)
                .doUpdate()
                .set(QUESTION_TAG_CURRENT_PROJECTION.TAXONOMY_VERSION_ID, authority.taxonomyVersionId())
                .set(QUESTION_TAG_CURRENT_PROJECTION.CURRENT_SNAPSHOT_ID, authority.currentSnapshotId())
                .set(QUESTION_TAG_CURRENT_PROJECTION.PRIMARY_NODE_ID, authority.primaryNodeId())
                .set(QUESTION_TAG_CURRENT_PROJECTION.DECISION_SOURCE, authority.decisionSource())
                .set(QUESTION_TAG_CURRENT_PROJECTION.TAG_STATUS, authority.status())
                .set(QUESTION_TAG_CURRENT_PROJECTION.AUTHORITY_STATE_VERSION, authority.stateVersion())
                .set(QUESTION_TAG_CURRENT_PROJECTION.LABEL_SET_HASH, authority.labelSetHash())
                .set(QUESTION_TAG_CURRENT_PROJECTION.PROJECTION_SEMANTIC_HASH, semanticHash)
                .set(QUESTION_TAG_CURRENT_PROJECTION.PROJECTED_AT, projectedAt)
                .where(QUESTION_TAG_CURRENT_PROJECTION.AUTHORITY_STATE_VERSION.lt(authority.stateVersion()))
                .execute();
        if (changed == 0) {
            assertExistingTag(authority, semanticHash);
            return;
        }
        database.deleteFrom(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY)
                .where(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY.PROJECTION_ID.eq(projectionId))
                .execute();
        for (int index = 0; index < authority.secondaryNodeIds().size(); index++) {
            database.insertInto(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY)
                    .set(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY.PROJECTION_ID, projectionId)
                    .set(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY.WORKSPACE_ID, authority.workspaceId())
                    .set(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY.TAXONOMY_VERSION_ID,
                            authority.taxonomyVersionId())
                    .set(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY.TAXONOMY_NODE_ID,
                            authority.secondaryNodeIds().get(index))
                    .set(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY.POSITION_INDEX, index)
                    .execute();
        }
    }

    @Override
    public void upsertDifficulty(
            DifficultyAuthority authority, UUID projectionId, String semanticHash, OffsetDateTime projectedAt) {
        enableWriter();
        int changed = database.insertInto(QUESTION_DIFFICULTY_CURRENT_PROJECTION)
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.PROJECTION_ID, projectionId)
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.WORKSPACE_ID, authority.workspaceId())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.QUESTION_ID, authority.questionId())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.QUESTION_REVISION_ID, authority.questionRevisionId())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.RUBRIC_KEY, authority.rubricKey())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.RUBRIC_VERSION_ID, authority.rubricVersionId())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.CONTEXT_KEY, authority.contextKey())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.CONTEXT_HASH, authority.contextHash())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.CURRENT_SNAPSHOT_ID, authority.currentSnapshotId())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.DIFFICULTY_VALUE,
                        authority.difficultyValue() == null ? null : authority.difficultyValue().shortValue())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.DECISION_SOURCE, authority.decisionSource())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.DIFFICULTY_STATUS, authority.status())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.AUTHORITY_STATE_VERSION, authority.stateVersion())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.PROJECTION_SEMANTIC_HASH, semanticHash)
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.PROJECTED_AT, projectedAt)
                .onConflict(QUESTION_DIFFICULTY_CURRENT_PROJECTION.WORKSPACE_ID,
                        QUESTION_DIFFICULTY_CURRENT_PROJECTION.QUESTION_REVISION_ID,
                        QUESTION_DIFFICULTY_CURRENT_PROJECTION.RUBRIC_KEY,
                        QUESTION_DIFFICULTY_CURRENT_PROJECTION.CONTEXT_KEY)
                .doUpdate()
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.RUBRIC_VERSION_ID, authority.rubricVersionId())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.CONTEXT_HASH, authority.contextHash())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.CURRENT_SNAPSHOT_ID, authority.currentSnapshotId())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.DIFFICULTY_VALUE,
                        authority.difficultyValue() == null ? null : authority.difficultyValue().shortValue())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.DECISION_SOURCE, authority.decisionSource())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.DIFFICULTY_STATUS, authority.status())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.AUTHORITY_STATE_VERSION, authority.stateVersion())
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.PROJECTION_SEMANTIC_HASH, semanticHash)
                .set(QUESTION_DIFFICULTY_CURRENT_PROJECTION.PROJECTED_AT, projectedAt)
                .where(QUESTION_DIFFICULTY_CURRENT_PROJECTION.AUTHORITY_STATE_VERSION.lt(authority.stateVersion()))
                .execute();
        if (changed == 0) assertExistingDifficulty(authority, semanticHash);
    }

    @Override
    public void markProcessed(UUID eventId, String workerId, OffsetDateTime processedAt) {
        int changed = database.update(GOVERNANCE_PROJECTION_OUTBOX)
                .set(GOVERNANCE_PROJECTION_OUTBOX.STATUS, "processed")
                .set(GOVERNANCE_PROJECTION_OUTBOX.LEASE_OWNER, (String) null)
                .set(GOVERNANCE_PROJECTION_OUTBOX.LEASE_UNTIL, (OffsetDateTime) null)
                .set(GOVERNANCE_PROJECTION_OUTBOX.PROCESSED_AT, processedAt)
                .set(GOVERNANCE_PROJECTION_OUTBOX.LAST_ERROR, (String) null)
                .where(GOVERNANCE_PROJECTION_OUTBOX.EVENT_ID.eq(eventId))
                .and(GOVERNANCE_PROJECTION_OUTBOX.STATUS.eq("processing"))
                .and(GOVERNANCE_PROJECTION_OUTBOX.LEASE_OWNER.eq(workerId))
                .execute();
        if (changed != 1) throw new IllegalStateException("governance_projection_lease_lost");
    }

    @Override
    public void markFailed(UUID eventId, String workerId, OffsetDateTime availableAt, String errorCode) {
        String safe = errorCode == null ? "projection_failed" : errorCode.substring(0, Math.min(2000, errorCode.length()));
        database.update(GOVERNANCE_PROJECTION_OUTBOX)
                .set(GOVERNANCE_PROJECTION_OUTBOX.STATUS, "failed")
                .set(GOVERNANCE_PROJECTION_OUTBOX.LEASE_OWNER, (String) null)
                .set(GOVERNANCE_PROJECTION_OUTBOX.LEASE_UNTIL, (OffsetDateTime) null)
                .set(GOVERNANCE_PROJECTION_OUTBOX.PROCESSED_AT, (OffsetDateTime) null)
                .set(GOVERNANCE_PROJECTION_OUTBOX.AVAILABLE_AT, availableAt)
                .set(GOVERNANCE_PROJECTION_OUTBOX.LAST_ERROR, safe)
                .where(GOVERNANCE_PROJECTION_OUTBOX.EVENT_ID.eq(eventId))
                .and(GOVERNANCE_PROJECTION_OUTBOX.STATUS.eq("processing"))
                .and(GOVERNANCE_PROJECTION_OUTBOX.LEASE_OWNER.eq(workerId))
                .execute();
    }

    @Override
    public List<UUID> lockTagStateIds(UUID workspaceId) {
        return database.select(QUESTION_TAG_STATE.STATE_ID).from(QUESTION_TAG_STATE)
                .where(QUESTION_TAG_STATE.WORKSPACE_ID.eq(workspaceId))
                .orderBy(QUESTION_TAG_STATE.STATE_ID).forShare()
                .fetch(QUESTION_TAG_STATE.STATE_ID);
    }

    @Override
    public List<UUID> lockDifficultyStateIds(UUID workspaceId) {
        return database.select(QUESTION_DIFFICULTY_STATE.STATE_ID).from(QUESTION_DIFFICULTY_STATE)
                .where(QUESTION_DIFFICULTY_STATE.WORKSPACE_ID.eq(workspaceId))
                .orderBy(QUESTION_DIFFICULTY_STATE.STATE_ID).forShare()
                .fetch(QUESTION_DIFFICULTY_STATE.STATE_ID);
    }

    @Override
    public void clearWorkspace(UUID workspaceId) {
        enableWriter();
        database.deleteFrom(QUESTION_TAG_CURRENT_PROJECTION)
                .where(QUESTION_TAG_CURRENT_PROJECTION.WORKSPACE_ID.eq(workspaceId)).execute();
        database.deleteFrom(QUESTION_DIFFICULTY_CURRENT_PROJECTION)
                .where(QUESTION_DIFFICULTY_CURRENT_PROJECTION.WORKSPACE_ID.eq(workspaceId)).execute();
    }

    @Override
    public List<UUID> maintenanceWorkspaces(UUID actorUserId, UUID requestedWorkspaceId) {
        Condition condition = WORKSPACE_MEMBER.USER_ID.eq(actorUserId)
                .and(WORKSPACE_MEMBER.STATUS.eq("active"))
                .and(WORKSPACE_MEMBER.MEMBER_ROLE.in("owner", "admin"));
        if (requestedWorkspaceId != null) condition = condition.and(WORKSPACE_MEMBER.WORKSPACE_ID.eq(requestedWorkspaceId));
        return database.select(WORKSPACE_MEMBER.WORKSPACE_ID).from(WORKSPACE_MEMBER)
                .where(condition).orderBy(WORKSPACE_MEMBER.WORKSPACE_ID)
                .fetch(WORKSPACE_MEMBER.WORKSPACE_ID);
    }

    @Override
    public List<UUID> queryQuestionRevisionIds(GovernanceQuery query, UUID cursor, int fetchLimit) {
        Condition condition = QUESTION_REVISION.WORKSPACE_ID.eq(query.workspaceId());
        if (!query.subject().isBlank()) condition = condition.and(QUESTION_REVISION.SUBJECT.eq(query.subject()));
        if (!query.stage().isBlank()) condition = condition.and(QUESTION_REVISION.STAGE.eq(query.stage()));
        if (cursor != null) condition = condition.and(QUESTION_REVISION.QUESTION_REVISION_ID.gt(cursor));

        boolean tagFilter = !query.taxonomyKey().isBlank()
                || query.primaryTagId() != null || query.secondaryTagId() != null;
        if (tagFilter) {
            Condition tag = QUESTION_TAG_CURRENT_PROJECTION.WORKSPACE_ID.eq(query.workspaceId())
                    .and(QUESTION_TAG_CURRENT_PROJECTION.QUESTION_REVISION_ID
                            .eq(QUESTION_REVISION.QUESTION_REVISION_ID));
            if (!query.taxonomyKey().isBlank()) {
                tag = tag.and(QUESTION_TAG_CURRENT_PROJECTION.TAXONOMY_KEY.eq(query.taxonomyKey()));
            }
            if (query.primaryTagId() != null) {
                tag = tag.and(QUESTION_TAG_CURRENT_PROJECTION.PRIMARY_NODE_ID.eq(query.primaryTagId()));
            }
            if (query.secondaryTagId() != null) {
                tag = tag.andExists(database.selectOne()
                        .from(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY)
                        .where(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY.PROJECTION_ID
                                .eq(QUESTION_TAG_CURRENT_PROJECTION.PROJECTION_ID))
                        .and(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY.TAXONOMY_NODE_ID
                                .eq(query.secondaryTagId())));
            }
            condition = condition.andExists(database.selectOne()
                    .from(QUESTION_TAG_CURRENT_PROJECTION).where(tag));
        }

        boolean difficultyFilter = !query.rubricKey().isBlank()
                || !query.difficultyContextKey().isBlank() || query.difficultyValue() != null;
        if (difficultyFilter) {
            Condition difficulty = QUESTION_DIFFICULTY_CURRENT_PROJECTION.WORKSPACE_ID.eq(query.workspaceId())
                    .and(QUESTION_DIFFICULTY_CURRENT_PROJECTION.QUESTION_REVISION_ID
                            .eq(QUESTION_REVISION.QUESTION_REVISION_ID));
            if (!query.rubricKey().isBlank()) {
                difficulty = difficulty.and(QUESTION_DIFFICULTY_CURRENT_PROJECTION.RUBRIC_KEY.eq(query.rubricKey()));
            }
            if (!query.difficultyContextKey().isBlank()) {
                difficulty = difficulty.and(QUESTION_DIFFICULTY_CURRENT_PROJECTION.CONTEXT_KEY
                        .eq(query.difficultyContextKey()));
            }
            if (query.difficultyValue() != null) {
                difficulty = difficulty.and(QUESTION_DIFFICULTY_CURRENT_PROJECTION.DIFFICULTY_VALUE
                        .eq(query.difficultyValue().shortValue()));
            }
            condition = condition.andExists(database.selectOne()
                    .from(QUESTION_DIFFICULTY_CURRENT_PROJECTION).where(difficulty));
        }
        return database.select(QUESTION_REVISION.QUESTION_REVISION_ID).from(QUESTION_REVISION)
                .where(condition).orderBy(QUESTION_REVISION.QUESTION_REVISION_ID)
                .limit(fetchLimit).fetch(QUESTION_REVISION.QUESTION_REVISION_ID);
    }

    @Override
    public List<TagProjectionView> findTagProjections(UUID workspaceId, UUID questionRevisionId) {
        return database.selectFrom(QUESTION_TAG_CURRENT_PROJECTION)
                .where(QUESTION_TAG_CURRENT_PROJECTION.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_TAG_CURRENT_PROJECTION.QUESTION_REVISION_ID.eq(questionRevisionId))
                .orderBy(QUESTION_TAG_CURRENT_PROJECTION.TAXONOMY_KEY)
                .fetch(record -> new TagProjectionView(
                        record.getTaxonomyKey(), record.getTaxonomyVersionId(), record.getCurrentSnapshotId(),
                        record.getPrimaryNodeId(), secondary(record.getProjectionId()), record.getDecisionSource(),
                        record.getTagStatus(), record.getAuthorityStateVersion(), record.getLabelSetHash(),
                        record.getProjectionSemanticHash()));
    }

    @Override
    public List<DifficultyProjectionView> findDifficultyProjections(UUID workspaceId, UUID questionRevisionId) {
        return database.selectFrom(QUESTION_DIFFICULTY_CURRENT_PROJECTION)
                .where(QUESTION_DIFFICULTY_CURRENT_PROJECTION.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_DIFFICULTY_CURRENT_PROJECTION.QUESTION_REVISION_ID.eq(questionRevisionId))
                .orderBy(QUESTION_DIFFICULTY_CURRENT_PROJECTION.RUBRIC_KEY,
                        QUESTION_DIFFICULTY_CURRENT_PROJECTION.CONTEXT_KEY)
                .fetch(record -> new DifficultyProjectionView(
                        record.getRubricKey(), record.getRubricVersionId(), record.getContextKey(),
                        record.getDifficultyValue() == null ? null : record.getDifficultyValue().intValue(),
                        record.getDecisionSource(), record.getDifficultyStatus(), record.getAuthorityStateVersion(),
                        record.getProjectionSemanticHash()));
    }

    @Override
    public ProjectionHealthResponse health(UUID workspaceId, OffsetDateTime now) {
        Record value = database.fetchOne("""
                select
                  count(*) filter (where status='pending')::bigint pending_count,
                  count(*) filter (where status='failed')::bigint failed_count,
                  extract(epoch from (?::timestamptz - min(created_at)
                    filter (where status in ('pending','failed'))))::bigint oldest_age,
                  max(processed_at) filter (where status='processed') last_success,
                  (select count(*) from teachbase_app.question_tag_state states
                    left join teachbase_app.question_tag_current_projection projections
                      on projections.workspace_id=states.workspace_id
                     and projections.question_revision_id=states.question_revision_id
                     and projections.taxonomy_key=states.taxonomy_key
                    where states.workspace_id=? and
                      (projections.projection_id is null
                       or projections.authority_state_version < states.state_version))::bigint tag_lag,
                  (select count(*) from teachbase_app.question_difficulty_state states
                    left join teachbase_app.question_difficulty_current_projection projections
                      on projections.workspace_id=states.workspace_id
                     and projections.question_revision_id=states.question_revision_id
                     and projections.rubric_key=states.rubric_key
                     and projections.context_key=states.context_key
                    where states.workspace_id=? and
                      (projections.projection_id is null
                       or projections.authority_state_version < states.state_version))::bigint difficulty_lag
                from teachbase_app.governance_projection_outbox
                where workspace_id=?
                """, now, workspaceId, workspaceId, workspaceId);
        return new ProjectionHealthResponse(
                workspaceId, value.get("pending_count", Long.class), value.get("failed_count", Long.class),
                value.get("oldest_age", Long.class), value.get("last_success", OffsetDateTime.class),
                value.get("tag_lag", Long.class), value.get("difficulty_lag", Long.class));
    }

    private void assertExistingTag(TagAuthority authority, String semanticHash) {
        var existing = database.select(
                        QUESTION_TAG_CURRENT_PROJECTION.AUTHORITY_STATE_VERSION,
                        QUESTION_TAG_CURRENT_PROJECTION.PROJECTION_SEMANTIC_HASH)
                .from(QUESTION_TAG_CURRENT_PROJECTION)
                .where(QUESTION_TAG_CURRENT_PROJECTION.WORKSPACE_ID.eq(authority.workspaceId()))
                .and(QUESTION_TAG_CURRENT_PROJECTION.QUESTION_REVISION_ID.eq(authority.questionRevisionId()))
                .and(QUESTION_TAG_CURRENT_PROJECTION.TAXONOMY_KEY.eq(authority.taxonomyKey()))
                .fetchOne();
        if (existing == null || (existing.get(QUESTION_TAG_CURRENT_PROJECTION.AUTHORITY_STATE_VERSION)
                == authority.stateVersion()
                && !existing.get(QUESTION_TAG_CURRENT_PROJECTION.PROJECTION_SEMANTIC_HASH).equals(semanticHash))) {
            throw new IllegalStateException("tag_projection_same_version_conflict");
        }
    }

    private void assertExistingDifficulty(DifficultyAuthority authority, String semanticHash) {
        var existing = database.select(
                        QUESTION_DIFFICULTY_CURRENT_PROJECTION.AUTHORITY_STATE_VERSION,
                        QUESTION_DIFFICULTY_CURRENT_PROJECTION.PROJECTION_SEMANTIC_HASH)
                .from(QUESTION_DIFFICULTY_CURRENT_PROJECTION)
                .where(QUESTION_DIFFICULTY_CURRENT_PROJECTION.WORKSPACE_ID.eq(authority.workspaceId()))
                .and(QUESTION_DIFFICULTY_CURRENT_PROJECTION.QUESTION_REVISION_ID.eq(authority.questionRevisionId()))
                .and(QUESTION_DIFFICULTY_CURRENT_PROJECTION.RUBRIC_KEY.eq(authority.rubricKey()))
                .and(QUESTION_DIFFICULTY_CURRENT_PROJECTION.CONTEXT_KEY.eq(authority.contextKey()))
                .fetchOne();
        if (existing == null || (existing.get(QUESTION_DIFFICULTY_CURRENT_PROJECTION.AUTHORITY_STATE_VERSION)
                == authority.stateVersion()
                && !existing.get(QUESTION_DIFFICULTY_CURRENT_PROJECTION.PROJECTION_SEMANTIC_HASH)
                        .equals(semanticHash))) {
            throw new IllegalStateException("difficulty_projection_same_version_conflict");
        }
    }

    private List<UUID> secondary(UUID projectionId) {
        return database.select(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY.TAXONOMY_NODE_ID)
                .from(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY)
                .where(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY.PROJECTION_ID.eq(projectionId))
                .orderBy(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY.POSITION_INDEX)
                .fetch(QUESTION_TAG_CURRENT_PROJECTION_SECONDARY.TAXONOMY_NODE_ID);
    }

    private ClaimedEvent event(Record value, String workerId) {
        return new ClaimedEvent(
                value.get("event_id", UUID.class), value.get("workspace_id", UUID.class),
                value.get("question_revision_id", UUID.class), value.get("domain", String.class),
                value.get("authority_state_id", UUID.class), value.get("authority_state_version", Long.class),
                value.get("event_key", String.class), value.get("attempt_count", Integer.class), workerId);
    }

    private void enableWriter() {
        database.fetch("select set_config('teachbase.governance_projection_writer','on',true)");
    }
}
