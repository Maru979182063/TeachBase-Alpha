package com.teachbase.server.taxonomy.api;

import com.teachbase.server.taxonomy.application.TaxonomyService;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 中文维护说明：本文件属于知识体系版本模块的对外稳定合同层，只负责 HTTP 协议转换，业务不变量必须留在应用服务中。
 *
 * 英文术语对照：HTTP boundary for taxonomy version lifecycle and question assignments.
 */
@RestController
@RequestMapping("/api/v1/taxonomies")
class TaxonomyController {

    private final TaxonomyService service;

    TaxonomyController(TaxonomyService service) {
        this.service = service;
    }

    @PostMapping("/versions")
    ResponseEntity<TaxonomyVersionResponse> createVersion(
            @Valid @RequestBody CreateTaxonomyVersionRequest request) {
        return ResponseEntity.ok(service.createVersion(request));
    }

    @PostMapping("/versions/{taxonomyVersionId}/nodes")
    ResponseEntity<TaxonomyNodeResponse> createNode(
            @PathVariable UUID taxonomyVersionId,
            @Valid @RequestBody CreateTaxonomyNodeRequest request) {
        return ResponseEntity.ok(service.createNode(taxonomyVersionId, request));
    }

    @PostMapping("/versions/{taxonomyVersionId}/activate")
    ResponseEntity<TaxonomyVersionResponse> activate(
            @PathVariable UUID taxonomyVersionId,
            @Valid @RequestBody ActivateTaxonomyVersionRequest request) {
        return ResponseEntity.ok(service.activate(taxonomyVersionId, request));
    }

    @org.springframework.web.bind.annotation.GetMapping("/versions/{taxonomyVersionId}/resolve")
    TaxonomyNodeResponse resolve(
            @PathVariable UUID taxonomyVersionId,
            @RequestParam UUID workspaceId,
            @RequestParam UUID actorUserId,
            @RequestParam String codeOrAlias) {
        return service.resolve(new ResolveTaxonomyNodeRequest(
                workspaceId, actorUserId, taxonomyVersionId, codeOrAlias));
    }

    @PostMapping("/assignments")
    ResponseEntity<QuestionTaxonomyLinkResponse> assign(
            @Valid @RequestBody AssignQuestionTaxonomyRequest request) {
        return ResponseEntity.ok(service.assign(request));
    }
}
