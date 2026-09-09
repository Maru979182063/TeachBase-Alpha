package com.teachbase.server.standardmodule.api;

import com.teachbase.server.standardmodule.application.StandardModuleService;
import jakarta.validation.Valid;
import java.net.URI;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** 中文维护说明：标准模块 HTTP 边界只做协议转换，业务不变量留在应用服务。 */
@RestController
@RequestMapping("/api/v1/standard-modules")
class StandardModuleController {

    private final StandardModuleService service;

    StandardModuleController(StandardModuleService service) {
        this.service = service;
    }

    @PostMapping
    ResponseEntity<StandardModuleResponse> create(@Valid @RequestBody CreateStandardModuleRequest request) {
        var result = service.create(request);
        if (result.createdModule()) {
            return ResponseEntity.created(URI.create("/api/v1/standard-modules/" + result.standardModuleId()))
                    .body(result);
        }
        return ResponseEntity.ok(result);
    }

    @PostMapping("/{standardModuleId}/revisions")
    ResponseEntity<StandardModuleResponse> revise(
            @PathVariable UUID standardModuleId,
            @Valid @RequestBody CreateStandardModuleRevisionRequest request) {
        return ResponseEntity.ok(service.revise(standardModuleId, request));
    }

    @PostMapping("/revisions/{standardModuleRevisionId}/sources")
    ResponseEntity<StandardModuleLinkResponse> linkSource(
            @PathVariable UUID standardModuleRevisionId,
            @Valid @RequestBody LinkStandardModuleSourceRequest request) {
        return ResponseEntity.ok(service.linkSource(standardModuleRevisionId, request));
    }

    @PostMapping("/revisions/{standardModuleRevisionId}/files")
    ResponseEntity<StandardModuleLinkResponse> linkFile(
            @PathVariable UUID standardModuleRevisionId,
            @Valid @RequestBody LinkStandardModuleFileRequest request) {
        return ResponseEntity.ok(service.linkFile(standardModuleRevisionId, request));
    }

    @GetMapping("/revisions/{standardModuleRevisionId}/usage")
    Map<String, Object> usage(
            @PathVariable UUID standardModuleRevisionId,
            @RequestParam UUID workspaceId,
            @RequestParam UUID actorUserId) {
        return Map.of("standardModuleRevisionId", standardModuleRevisionId,
                "occurrenceCount", service.usageCount(workspaceId, actorUserId, standardModuleRevisionId));
    }
}
