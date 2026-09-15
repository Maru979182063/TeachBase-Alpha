package com.teachbase.server.governanceprojection.application;

import static com.teachbase.server.governanceprojection.api.GovernanceProjectionContracts.*;
import static com.teachbase.server.governanceprojection.application.GovernanceProjectionHasher.*;

import com.teachbase.server.governanceprojection.application.GovernanceProjectionRepository.GovernanceQuery;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 中文维护说明：查询只读 projection；重建只读 authority，并且不消费 legacy fallback。 */
@Service
public class GovernanceProjectionService {

    private final WorkspaceDirectory workspaces;
    private final GovernanceProjectionRepository repository;

    public GovernanceProjectionService(
            WorkspaceDirectory workspaces, GovernanceProjectionRepository repository) {
        this.workspaces = workspaces;
        this.repository = repository;
    }

    @Transactional(readOnly = true)
    public GovernanceQueryResponse query(
            UUID workspaceId, UUID actorUserId, String subject, String stage,
            String taxonomyKey, UUID primaryTagId, UUID secondaryTagId,
            String rubricKey, String difficultyContextKey, Integer difficultyValue,
            String cursorValue, int requestedLimit) {
        requireMember(workspaceId, actorUserId);
        int limit = requestedLimit == 0 ? 30 : requestedLimit;
        if (limit < 1 || limit > 100) {
            throw new GovernanceProjectionValidationException("governance_query_limit_invalid");
        }
        if (difficultyValue != null && (difficultyValue < 1 || difficultyValue > 5)) {
            throw new GovernanceProjectionValidationException("governance_query_difficulty_invalid");
        }
        UUID cursor = cursor(cursorValue);
        var filter = new GovernanceQuery(
                workspaceId, clean(subject), clean(stage), clean(taxonomyKey), primaryTagId, secondaryTagId,
                clean(rubricKey), clean(difficultyContextKey), difficultyValue);
        List<UUID> ids = repository.queryQuestionRevisionIds(filter, cursor, limit + 1);
        String nextCursor = null;
        if (ids.size() > limit) {
            nextCursor = ids.get(limit - 1).toString();
            ids = new ArrayList<>(ids.subList(0, limit));
        }
        List<GovernanceQueryItem> items = ids.stream()
                .map(id -> new GovernanceQueryItem(
                        id, repository.findTagProjections(workspaceId, id),
                        repository.findDifficultyProjections(workspaceId, id)))
                .toList();
        return new GovernanceQueryResponse(items, limit, nextCursor);
    }

    @Transactional
    public RebuildResponse rebuild(RebuildRequest request) {
        List<UUID> permitted = repository.maintenanceWorkspaces(request.actorUserId(), request.workspaceId());
        if (permitted.isEmpty()) throw new GovernanceProjectionAccessException();
        int tags = 0;
        int difficulties = 0;
        for (UUID workspaceId : permitted) {
            List<UUID> tagStates = repository.lockTagStateIds(workspaceId);
            List<UUID> difficultyStates = repository.lockDifficultyStateIds(workspaceId);
            repository.clearWorkspace(workspaceId);
            for (UUID stateId : tagStates) {
                TagAuthority authority = repository.loadTagAuthority(stateId, false)
                        .orElseThrow(() -> new IllegalStateException("tag_projection_authority_missing"));
                repository.upsertTag(
                        authority,
                        stableProjectionId("TAG", authority.workspaceId(), authority.questionRevisionId(),
                                authority.taxonomyKey()),
                        tagHash(authority), now());
                tags++;
            }
            for (UUID stateId : difficultyStates) {
                DifficultyAuthority authority = repository.loadDifficultyAuthority(stateId, false)
                        .orElseThrow(() -> new IllegalStateException("difficulty_projection_authority_missing"));
                repository.upsertDifficulty(
                        authority,
                        stableProjectionId("DIFFICULTY", authority.workspaceId(), authority.questionRevisionId(),
                                authority.rubricKey() + "|" + authority.contextKey()),
                        difficultyHash(authority), now());
                difficulties++;
            }
        }
        return new RebuildResponse(permitted.size(), tags, difficulties);
    }

    @Transactional(readOnly = true)
    public ProjectionHealthResponse health(UUID workspaceId, UUID actorUserId) {
        requireMember(workspaceId, actorUserId);
        return repository.health(workspaceId, now());
    }

    private void requireMember(UUID workspaceId, UUID actorUserId) {
        if (workspaces.activeMemberRole(workspaceId, actorUserId).isEmpty()) {
            throw new GovernanceProjectionAccessException();
        }
    }

    private UUID cursor(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return UUID.fromString(value.trim());
        } catch (IllegalArgumentException exception) {
            throw new GovernanceProjectionValidationException("governance_query_cursor_invalid");
        }
    }

    private String clean(String value) {
        return value == null ? "" : value.trim();
    }

    private OffsetDateTime now() {
        return OffsetDateTime.now(ZoneOffset.UTC);
    }
}
