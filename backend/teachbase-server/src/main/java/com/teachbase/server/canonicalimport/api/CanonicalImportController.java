package com.teachbase.server.canonicalimport.api;

import com.teachbase.server.canonicalimport.application.CanonicalImportService;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** 中文维护说明：唯一正式内容收货 HTTP 边界，所有动作都要求 workspace 与 actor。 */
@RestController
@RequestMapping("/api/v1/content-imports")
class CanonicalImportController {

    private final CanonicalImportService service;

    CanonicalImportController(CanonicalImportService service) {
        this.service = service;
    }

    @PostMapping("/validate")
    ResponseEntity<CanonicalImportStatusResponse> validate(
            @Valid @RequestBody ValidateCanonicalImportRequest request) {
        return ResponseEntity.ok(service.validate(request));
    }

    @PostMapping("/{importRequestId}/commit")
    ResponseEntity<CanonicalImportStatusResponse> commit(
            @PathVariable UUID importRequestId,
            @Valid @RequestBody CanonicalImportActionRequest request) {
        return ResponseEntity.ok(service.commit(importRequestId, request));
    }

    @GetMapping("/{importRequestId}")
    CanonicalImportStatusResponse status(
            @PathVariable UUID importRequestId,
            @RequestParam UUID workspaceId,
            @RequestParam UUID actorUserId) {
        return service.status(importRequestId, workspaceId, actorUserId);
    }

    @PostMapping("/{importRequestId}/resume")
    ResponseEntity<CanonicalImportStatusResponse> resume(
            @PathVariable UUID importRequestId,
            @Valid @RequestBody CanonicalImportActionRequest request) {
        return ResponseEntity.ok(service.resume(importRequestId, request));
    }

    @PostMapping("/{importRequestId}/verify")
    ResponseEntity<CanonicalImportStatusResponse> verify(
            @PathVariable UUID importRequestId,
            @Valid @RequestBody CanonicalImportActionRequest request) {
        return ResponseEntity.ok(service.verify(importRequestId, request));
    }
}
