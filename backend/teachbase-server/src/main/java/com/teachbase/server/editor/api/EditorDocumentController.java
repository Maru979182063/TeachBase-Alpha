package com.teachbase.server.editor.api;

import com.teachbase.server.editor.application.CreateEditorDocumentCommand;
import com.teachbase.server.editor.application.CreateEditorSnapshotCommand;
import com.teachbase.server.editor.application.EditorClientUpgradeRequiredException;
import com.teachbase.server.editor.application.EditorContentValidationException;
import com.teachbase.server.editor.application.EditorDocumentService;
import com.teachbase.server.editor.application.EditorQuestionPlacementService;
import com.teachbase.server.editor.application.UpdateEditorDraftCommand;
import jakarta.validation.Valid;
import java.net.URI;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/editor/documents")
/**
 * 中文维护说明：本文件属于在线编辑文档模块的对外稳定合同层，只负责 HTTP 协议转换，业务不变量必须留在应用服务中。
 *
 * 英文术语对照：HTTP adapter for editor creation, optimistic saves, placement, and snapshots.
 */
class EditorDocumentController {

    private final EditorDocumentService service;
    private final EditorQuestionPlacementService questionPlacement;

    EditorDocumentController(EditorDocumentService service, EditorQuestionPlacementService questionPlacement) {
        this.service = service;
        this.questionPlacement = questionPlacement;
    }

    @PostMapping
    ResponseEntity<EditorDraftResponse> create(@Valid @RequestBody CreateEditorDocumentRequest request) {
        var draft = service.create(new CreateEditorDocumentCommand(
                request.workspaceId(), request.actorUserId(), request.documentKind(), request.title(),
                request.schemaVersion(), request.masterDoc(), request.versionOverrides()));
        return ResponseEntity
                .created(URI.create("/api/v1/editor/documents/" + draft.editorDocumentId()))
                .eTag(etag(draft.draftVersion()))
                .body(EditorDraftResponse.from(draft));
    }

    @PutMapping("/{documentId}/draft")
    ResponseEntity<EditorDraftResponse> update(
            @PathVariable UUID documentId,
            @Valid @RequestBody UpdateEditorDraftRequest request) {
        var draft = service.update(new UpdateEditorDraftCommand(
                documentId, request.workspaceId(), request.actorUserId(), requireDraftVersion(
                        request.expectedDraftVersion(), request.expectedRevisionNo()),
                request.clientMutationId(), request.schemaVersion(), request.masterDoc(), request.versionOverrides()));
        return ResponseEntity.ok().eTag(etag(draft.draftVersion())).body(EditorDraftResponse.from(draft));
    }

    @GetMapping("/{documentId}/draft")
    ResponseEntity<EditorDraftResponse> get(
            @PathVariable UUID documentId,
            @RequestParam UUID workspaceId,
            @RequestParam UUID actorUserId) {
        var draft = service.get(documentId, workspaceId, actorUserId);
        return ResponseEntity.ok().eTag(etag(draft.draftVersion())).body(EditorDraftResponse.from(draft));
    }

    @PostMapping("/{documentId}/snapshots")
    ResponseEntity<EditorSnapshotResponse> createSnapshot(
            @PathVariable UUID documentId,
            @Valid @RequestBody CreateEditorSnapshotRequest request) {
        var snapshot = service.createSnapshot(new CreateEditorSnapshotCommand(
                documentId, request.workspaceId(), request.actorUserId(), requireDraftVersion(
                        request.expectedDraftVersion(), request.expectedRevisionNo()),
                request.variantKey(), request.audience(), request.schemaVersion()));
        return ResponseEntity
                .created(URI.create("/api/v1/editor/snapshots/" + snapshot.editorSnapshotId()))
                .body(EditorSnapshotResponse.from(snapshot));
    }

    @PostMapping("/{documentId}/question-references")
    ResponseEntity<EditorDraftResponse> placeQuestionReferences(
            @PathVariable UUID documentId,
            @Valid @RequestBody PlaceQuestionReferencesRequest request) {
        requireDraftVersion(request.expectedDraftVersion(), request.expectedRevisionNo());
        var draft = questionPlacement.place(documentId, request);
        return ResponseEntity.ok().eTag(etag(draft.draftVersion())).body(EditorDraftResponse.from(draft));
    }

    private String etag(long draftVersion) {
        return "\"draft-" + draftVersion + "\"";
    }

    /**
     * 中文维护说明：灰度期不把旧 revision 号猜成 draft version；旧合同必须显式升级，缺字段则按新合同报错。
     */
    private long requireDraftVersion(Long expectedDraftVersion, Long expectedRevisionNo) {
        if (expectedDraftVersion != null && expectedRevisionNo != null) {
            throw new EditorContentValidationException("editor_draft_version_contract_ambiguous");
        }
        if (expectedDraftVersion != null) return expectedDraftVersion;
        if (expectedRevisionNo != null) throw new EditorClientUpgradeRequiredException();
        throw new EditorContentValidationException("expected_draft_version_required");
    }
}
