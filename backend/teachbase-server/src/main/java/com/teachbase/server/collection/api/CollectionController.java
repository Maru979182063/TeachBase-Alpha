package com.teachbase.server.collection.api;

import com.teachbase.server.collection.application.CollectionService;
import jakarta.validation.Valid;
import java.net.URI;
import java.util.UUID;
import java.util.List;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，只负责 HTTP 协议转换，业务不变量必须留在应用服务中。
 *
 * 英文术语对照：HTTP boundary for basket draft, autosave, and immutable snapshot workflows.
 */
@RestController
@RequestMapping("/api/v1/question-collections")
class CollectionController {

    private final CollectionService service;

    CollectionController(CollectionService service) {
        this.service = service;
    }

    @PostMapping
    ResponseEntity<CollectionDraftResponse> create(@Valid @RequestBody CreateCollectionRequest request) {
        var response = service.create(request.workspaceId(), request.actorUserId(), request.name());
        return ResponseEntity.created(URI.create("/api/v1/question-collections/" + response.questionCollectionId()))
                .eTag(etag(response.draftVersion())).body(response);
    }

    @GetMapping("/{collectionId}/draft")
    ResponseEntity<CollectionDraftResponse> get(
            @PathVariable UUID collectionId,
            @RequestParam UUID workspaceId,
            @RequestParam UUID actorUserId) {
        var response = service.get(collectionId, workspaceId, actorUserId);
        return ResponseEntity.ok().eTag(etag(response.draftVersion())).body(response);
    }

    @PutMapping("/{collectionId}/draft")
    ResponseEntity<CollectionDraftResponse> save(
            @PathVariable UUID collectionId,
            @Valid @RequestBody SaveCollectionDraftRequest request) {
        var response = service.save(collectionId, request);
        return ResponseEntity.ok().eTag(etag(response.draftVersion())).body(response);
    }

    @GetMapping("/{collectionId}/checkpoints")
    List<CollectionCheckpointResponse> checkpoints(
            @PathVariable UUID collectionId,
            @RequestParam UUID workspaceId,
            @RequestParam UUID actorUserId,
            @RequestParam(defaultValue = "20") int limit) {
        return service.checkpoints(collectionId, workspaceId, actorUserId, limit);
    }

    @PostMapping("/{collectionId}/checkpoints/{checkpointId}/restore")
    ResponseEntity<CollectionDraftResponse> restore(
            @PathVariable UUID collectionId,
            @PathVariable UUID checkpointId,
            @Valid @RequestBody RestoreCollectionCheckpointRequest request) {
        var response = service.restore(
                collectionId, checkpointId, request.workspaceId(), request.actorUserId(),
                request.expectedDraftVersion());
        return ResponseEntity.ok().eTag(etag(response.draftVersion())).body(response);
    }

    @PostMapping("/{collectionId}/snapshots")
    ResponseEntity<CollectionSnapshotResponse> snapshot(
            @PathVariable UUID collectionId,
            @Valid @RequestBody CreateCollectionSnapshotRequest request) {
        var response = service.snapshot(
                collectionId, request.workspaceId(), request.actorUserId(), request.expectedDraftVersion());
        return ResponseEntity.created(URI.create(
                "/api/v1/question-collections/" + collectionId + "/snapshots/"
                        + response.questionCollectionSnapshotId())).body(response);
    }

    private String etag(long version) {
        return "\"draft-" + version + "\"";
    }
}
