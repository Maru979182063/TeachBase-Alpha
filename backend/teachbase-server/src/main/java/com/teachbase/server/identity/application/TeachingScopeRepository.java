package com.teachbase.server.identity.application;

import com.teachbase.server.identity.api.TeachingScopeResponse;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * 成员角色与教学范围的持久化端口，替换操作由应用服务提供事务边界。
 */
public interface TeachingScopeRepository {

    Optional<String> activeMemberRole(UUID workspaceId, UUID userId);

    boolean lockActiveMember(UUID workspaceId, UUID userId);

    List<TeachingScopeResponse> findAll(UUID workspaceId, UUID userId);

    void replaceAll(
            UUID workspaceId,
            UUID userId,
            UUID actorUserId,
            List<TeachingScopeResponse> scopes);
}
