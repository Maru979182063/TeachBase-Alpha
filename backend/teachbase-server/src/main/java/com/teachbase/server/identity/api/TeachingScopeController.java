package com.teachbase.server.identity.api;

import com.teachbase.server.identity.application.TeachingScopeService;
import jakarta.validation.Valid;
import java.util.List;
import java.util.UUID;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 工作空间成员教学范围的 HTTP 入口，业务授权和整表替换由应用服务完成。
 */
@RestController
@RequestMapping("/api/v1/workspaces/{workspaceId}/members/{userId}/teaching-scopes")
class TeachingScopeController {

    private final TeachingScopeService service;

    TeachingScopeController(TeachingScopeService service) {
        this.service = service;
    }

    @GetMapping
    List<TeachingScopeResponse> findAll(
            @PathVariable UUID workspaceId,
            @PathVariable UUID userId,
            @RequestParam UUID actorUserId) {
        return service.findAll(workspaceId, userId, actorUserId);
    }

    @PutMapping
    List<TeachingScopeResponse> replace(
            @PathVariable UUID workspaceId,
            @PathVariable UUID userId,
            @Valid @RequestBody ReplaceTeachingScopesRequest request) {
        return service.replace(workspaceId, userId, request);
    }
}
