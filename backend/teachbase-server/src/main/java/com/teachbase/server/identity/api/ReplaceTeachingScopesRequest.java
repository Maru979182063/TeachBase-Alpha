package com.teachbase.server.identity.api;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.UUID;

/**
 * 整体替换成员教学范围的请求；空列表表示清空绑定。
 */
public record ReplaceTeachingScopesRequest(
        @NotNull UUID actorUserId,
        @NotNull @Size(max = 32) List<@Valid TeachingScopeRequest> scopes) {
}
