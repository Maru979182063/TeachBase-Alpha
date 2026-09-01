package com.teachbase.server.collection.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import com.teachbase.server.collection.api.CollectionDraftResponse;
import com.teachbase.server.collection.api.CollectionCheckpointResponse;
import com.teachbase.server.collection.api.CollectionItemRequest;
import com.teachbase.server.collection.api.CollectionSnapshotResponse;
import com.teachbase.server.collection.api.SaveCollectionDraftRequest;
import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import com.teachbase.server.question.api.QuestionRevisionDescriptor;
import com.teachbase.server.question.api.QuestionRevisionDirectory;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Transaction boundary for basket editing. It resolves every requested revision
 * explicitly and rejects unapproved content before persistence, keeping search,
 * placement, and publication on the same review contract.
 */
@Service
public class CollectionService {

    private final WorkspaceDirectory workspaces;
    private final QuestionRevisionDirectory revisions;
    private final CollectionRepository collections;
    private final AuditTrail auditTrail;

    public CollectionService(
            WorkspaceDirectory workspaces,
            QuestionRevisionDirectory revisions,
            CollectionRepository collections,
            AuditTrail auditTrail) {
        this.workspaces = workspaces;
        this.revisions = revisions;
        this.collections = collections;
        this.auditTrail = auditTrail;
    }

    @Transactional
    public CollectionDraftResponse create(UUID workspaceId, UUID actorUserId, String name) {
        validateWorkspaceActor(workspaceId, actorUserId);
        String normalizedName = name == null ? "" : name.trim();
        if (normalizedName.isBlank() || normalizedName.length() > 512) {
            throw new CollectionValidationException("question_collection_name_invalid");
        }
        var draft = collections.create(workspaceId, actorUserId, normalizedName);
        auditTrail.record(new AuditCommand(
                workspaceId, actorUserId, "question_collection.created", "question_collection",
                draft.questionCollectionId(), Map.of("name", normalizedName)));
        return response(draft);
    }

    @Transactional(readOnly = true)
    public CollectionDraftResponse get(UUID collectionId, UUID workspaceId, UUID actorUserId) {
        validateWorkspaceActor(workspaceId, actorUserId);
        return response(collections.find(collectionId, workspaceId).orElseThrow(CollectionNotFoundException::new));
    }

    @Transactional(readOnly = true)
    public List<CollectionCheckpointResponse> checkpoints(
            UUID collectionId, UUID workspaceId, UUID actorUserId, int requestedLimit) {
        validateWorkspaceActor(workspaceId, actorUserId);
        int limit = requestedLimit == 0 ? 20 : requestedLimit;
        if (limit < 1 || limit > 100) {
            throw new CollectionValidationException("question_collection_checkpoint_limit_invalid");
        }
        // Confirm aggregate visibility before exposing checkpoint history.
        collections.find(collectionId, workspaceId).orElseThrow(CollectionNotFoundException::new);
        return collections.listCheckpoints(collectionId, workspaceId, limit).stream()
                .map(checkpoint -> new CollectionCheckpointResponse(
                        checkpoint.checkpointId(), checkpoint.draftVersion(), checkpoint.checkpointKind(),
                        checkpoint.contentHash(), checkpoint.content(), checkpoint.createdAt(), checkpoint.expiresAt()))
                .toList();
    }

    @Transactional
    public CollectionDraftResponse save(UUID collectionId, SaveCollectionDraftRequest request) {
        validateWorkspaceActor(request.workspaceId(), request.actorUserId());
        if (request.expectedDraftVersion() < 0) {
            throw new CollectionValidationException("question_collection_version_invalid");
        }
        String kind = request.checkpointKind() == null ? "" : request.checkpointKind().trim();
        if (!kind.equals("autosave") && !kind.equals("manual")) {
            throw new CollectionValidationException("question_collection_checkpoint_kind_invalid");
        }
        List<UUID> revisionIds = request.items().stream().map(CollectionItemRequest::questionRevisionId).toList();
        List<QuestionRevisionDescriptor> resolved = resolveApproved(request.workspaceId(), revisionIds);
        List<JsonNode> settings = request.items().stream().map(CollectionItemRequest::settings).toList();
        if (settings.stream().anyMatch(value -> value == null || !value.isObject())) {
            throw new CollectionValidationException("question_collection_item_settings_invalid");
        }
        var draft = collections.save(
                collectionId, request.workspaceId(), request.actorUserId(), request.expectedDraftVersion(),
                kind, resolved, settings);
        auditTrail.record(new AuditCommand(
                request.workspaceId(), request.actorUserId(), "question_collection.saved", "question_collection",
                collectionId, Map.of("draftVersion", draft.draftVersion(), "checkpointKind", kind,
                        "itemCount", draft.items().size())));
        return response(draft);
    }

    @Transactional
    public CollectionSnapshotResponse snapshot(
            UUID collectionId, UUID workspaceId, UUID actorUserId, long expectedVersion) {
        validateWorkspaceActor(workspaceId, actorUserId);
        var current = collections.find(collectionId, workspaceId).orElseThrow(CollectionNotFoundException::new);
        if (expectedVersion != current.draftVersion()) {
            throw new CollectionVersionConflictException(current.draftVersion());
        }
        List<UUID> revisionIds = current.items().stream().map(item -> item.questionRevisionId()).toList();
        List<QuestionRevisionDescriptor> resolved = resolveApproved(workspaceId, revisionIds);
        var snapshot = collections.snapshot(
                collectionId, workspaceId, actorUserId, expectedVersion, resolved);
        auditTrail.record(new AuditCommand(
                workspaceId, actorUserId, "question_collection.snapshot_created", "question_collection_snapshot",
                snapshot.snapshotId(), Map.of("collectionId", collectionId.toString(),
                        "sourceDraftVersion", snapshot.sourceDraftVersion(), "contentHash", snapshot.contentHash())));
        return new CollectionSnapshotResponse(
                snapshot.snapshotId(), snapshot.collectionId(), snapshot.sourceDraftVersion(),
                snapshot.contentHash(), snapshot.frozenContent());
    }

    @Transactional
    public CollectionDraftResponse restore(
            UUID collectionId,
            UUID checkpointId,
            UUID workspaceId,
            UUID actorUserId,
            long expectedVersion) {
        validateWorkspaceActor(workspaceId, actorUserId);
        CollectionCheckpoint checkpoint = collections.findCheckpoint(collectionId, checkpointId, workspaceId)
                .orElseThrow(CollectionNotFoundException::new);
        JsonNode itemNodes = checkpoint.content().path("items");
        if (!itemNodes.isArray()) throw new CollectionValidationException("question_collection_checkpoint_invalid");
        var revisionIds = new java.util.ArrayList<UUID>();
        var settings = new java.util.ArrayList<JsonNode>();
        for (JsonNode item : itemNodes) {
            try {
                revisionIds.add(UUID.fromString(item.path("question").path("questionRevisionId").asText()));
            } catch (IllegalArgumentException exception) {
                throw new CollectionValidationException("question_collection_checkpoint_invalid");
            }
            JsonNode itemSettings = item.path("settings");
            if (!itemSettings.isObject()) {
                throw new CollectionValidationException("question_collection_checkpoint_invalid");
            }
            settings.add(itemSettings);
        }
        List<QuestionRevisionDescriptor> resolved = resolveApproved(workspaceId, revisionIds);
        var restored = collections.save(
                collectionId, workspaceId, actorUserId, expectedVersion, "restore", resolved, settings);
        auditTrail.record(new AuditCommand(
                workspaceId, actorUserId, "question_collection.restored", "question_collection",
                collectionId, Map.of("checkpointId", checkpointId.toString(),
                        "draftVersion", restored.draftVersion())));
        return response(restored);
    }

    private List<QuestionRevisionDescriptor> resolveApproved(UUID workspaceId, List<UUID> revisionIds) {
        if (revisionIds.size() != new HashSet<>(revisionIds).size()) {
            throw new CollectionValidationException("question_collection_duplicate_revision");
        }
        List<QuestionRevisionDescriptor> resolved = revisions.findAll(workspaceId, revisionIds);
        if (resolved.size() != revisionIds.size()) {
            throw new CollectionValidationException("question_revision_not_found");
        }
        if (resolved.stream().anyMatch(item -> !item.reviewStatus().equals("approved"))) {
            throw new CollectionValidationException("question_revision_not_approved");
        }
        var questionIds = resolved.stream().map(QuestionRevisionDescriptor::questionId).toList();
        if (questionIds.size() != new HashSet<>(questionIds).size()) {
            throw new CollectionValidationException("question_collection_duplicate_question");
        }
        return resolved;
    }

    private CollectionDraftResponse response(CollectionDraft draft) {
        return new CollectionDraftResponse(
                draft.questionCollectionId(), draft.workspaceId(), draft.name(), draft.status(),
                draft.draftVersion(), draft.items());
    }

    private void validateWorkspaceActor(UUID workspaceId, UUID actorUserId) {
        if (workspaceId == null) throw new CollectionValidationException("workspace_id_required");
        if (actorUserId == null) throw new CollectionValidationException("actor_user_id_required");
        if (!workspaces.exists(workspaceId)) throw new WorkspaceNotFoundException();
        if (!workspaces.isActiveMember(workspaceId, actorUserId)) throw new ActorNotWorkspaceMemberException();
    }
}
