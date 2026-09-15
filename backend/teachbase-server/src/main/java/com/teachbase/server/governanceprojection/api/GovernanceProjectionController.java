package com.teachbase.server.governanceprojection.api;

import static com.teachbase.server.governanceprojection.api.GovernanceProjectionContracts.*;

import com.teachbase.server.governanceprojection.application.GovernanceProjectionService;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** 中文维护说明：这是治理读取与内部维护边界，不替代既有全文搜索 API。 */
@RestController
@RequestMapping("/api/v1")
public class GovernanceProjectionController {

    private final GovernanceProjectionService service;

    public GovernanceProjectionController(GovernanceProjectionService service) {
        this.service = service;
    }

    @GetMapping("/questions/governance-query")
    public GovernanceQueryResponse query(
            @RequestParam UUID workspaceId,
            @RequestParam UUID actorUserId,
            @RequestParam(defaultValue = "") String subject,
            @RequestParam(defaultValue = "") String stage,
            @RequestParam(defaultValue = "") String taxonomyKey,
            @RequestParam(required = false) UUID primaryTagId,
            @RequestParam(required = false) UUID secondaryTagId,
            @RequestParam(defaultValue = "") String rubricKey,
            @RequestParam(defaultValue = "") String difficultyContextKey,
            @RequestParam(required = false) Integer difficultyValue,
            @RequestParam(defaultValue = "") String cursor,
            @RequestParam(defaultValue = "30") int limit) {
        return service.query(
                workspaceId, actorUserId, subject, stage, taxonomyKey, primaryTagId, secondaryTagId,
                rubricKey, difficultyContextKey, difficultyValue, cursor, limit);
    }

    @PostMapping("/internal/governance-projections/rebuild")
    public ResponseEntity<RebuildResponse> rebuild(@Valid @RequestBody RebuildRequest request) {
        return ResponseEntity.ok(service.rebuild(request));
    }

    @GetMapping("/internal/governance-projections/health")
    public ProjectionHealthResponse health(
            @RequestParam UUID workspaceId, @RequestParam UUID actorUserId) {
        return service.health(workspaceId, actorUserId);
    }
}
