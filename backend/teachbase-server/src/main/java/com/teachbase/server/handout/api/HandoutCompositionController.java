package com.teachbase.server.handout.api;

import com.teachbase.server.handout.application.HandoutCompositionService;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** 中文维护说明：讲义 composition HTTP 边界只接受精确 editor revision。 */
@RestController
@RequestMapping("/api/v1/handouts")
class HandoutCompositionController {

    private final HandoutCompositionService service;

    HandoutCompositionController(HandoutCompositionService service) {
        this.service = service;
    }

    @PostMapping("/{editorDocumentId}/revisions/{editorRevisionId}/composition")
    ResponseEntity<HandoutCompositionResponse> create(
            @PathVariable UUID editorDocumentId,
            @PathVariable UUID editorRevisionId,
            @Valid @RequestBody CreateHandoutCompositionRequest request) {
        return ResponseEntity.ok(service.create(editorDocumentId, editorRevisionId, request));
    }
}
