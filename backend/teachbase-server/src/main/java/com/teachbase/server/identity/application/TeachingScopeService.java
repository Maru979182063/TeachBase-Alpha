package com.teachbase.server.identity.application;

import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.ReplaceTeachingScopesRequest;
import com.teachbase.server.identity.api.TeachingScopeResponse;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 管理成员教学范围，并保证本人维护与管理员代管两种权限路径一致。
 */
@Service
public class TeachingScopeService {

    private static final Set<String> MANAGER_ROLES = Set.of("owner", "admin");
    private final TeachingScopeRepository repository;

    public TeachingScopeService(TeachingScopeRepository repository) {
        this.repository = repository;
    }

    @Transactional(readOnly = true)
    public List<TeachingScopeResponse> findAll(UUID workspaceId, UUID userId, UUID actorUserId) {
        authorize(workspaceId, userId, actorUserId, false);
        return repository.findAll(workspaceId, userId);
    }

    @Transactional
    public List<TeachingScopeResponse> replace(
            UUID workspaceId,
            UUID userId,
            ReplaceTeachingScopesRequest request) {
        authorize(workspaceId, userId, request.actorUserId(), true);
        if (!repository.lockActiveMember(workspaceId, userId)) {
            throw new TeachingScopeValidationException("teaching_scope_member_not_active");
        }

        var normalized = normalize(request.scopes());
        repository.replaceAll(workspaceId, userId, request.actorUserId(), normalized);
        return repository.findAll(workspaceId, userId);
    }

    private void authorize(UUID workspaceId, UUID userId, UUID actorUserId, boolean mutation) {
        var actorRole = repository.activeMemberRole(workspaceId, actorUserId)
                .orElseThrow(ActorNotWorkspaceMemberException::new);
        if (repository.activeMemberRole(workspaceId, userId).isEmpty()) {
            throw new TeachingScopeValidationException("teaching_scope_member_not_active");
        }
        if (mutation && !actorUserId.equals(userId) && !MANAGER_ROLES.contains(actorRole)) {
            throw new TeachingScopeValidationException("teaching_scope_forbidden");
        }
    }

    private List<TeachingScopeResponse> normalize(List<com.teachbase.server.identity.api.TeachingScopeRequest> scopes) {
        var keys = new HashSet<String>();
        int primaryCount = 0;
        var normalized = new java.util.ArrayList<TeachingScopeResponse>(scopes.size());
        for (var scope : scopes) {
            var subject = clean(scope.subject());
            var stage = clean(scope.stage());
            if (subject.isEmpty() || stage.isEmpty()) {
                throw new TeachingScopeValidationException("teaching_scope_blank_dimension");
            }
            if (!keys.add(subject + "\u0000" + stage)) {
                throw new TeachingScopeValidationException("teaching_scope_duplicate");
            }
            if (scope.primary() && ++primaryCount > 1) {
                throw new TeachingScopeValidationException("teaching_scope_multiple_primary");
            }
            normalized.add(new TeachingScopeResponse(subject, stage, scope.primary()));
        }
        return List.copyOf(normalized);
    }

    private String clean(String value) {
        return value == null ? "" : value.trim();
    }
}
