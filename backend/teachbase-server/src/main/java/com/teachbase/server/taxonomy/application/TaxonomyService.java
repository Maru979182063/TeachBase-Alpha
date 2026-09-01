package com.teachbase.server.taxonomy.application;

import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import com.teachbase.server.question.api.QuestionRevisionDirectory;
import com.teachbase.server.taxonomy.api.ActivateTaxonomyVersionRequest;
import com.teachbase.server.taxonomy.api.AssignQuestionTaxonomyRequest;
import com.teachbase.server.taxonomy.api.CreateTaxonomyNodeRequest;
import com.teachbase.server.taxonomy.api.CreateTaxonomyVersionRequest;
import com.teachbase.server.taxonomy.api.QuestionTaxonomyLinkResponse;
import com.teachbase.server.taxonomy.api.ResolveTaxonomyNodeRequest;
import com.teachbase.server.taxonomy.api.TaxonomyCatalog;
import com.teachbase.server.taxonomy.api.TaxonomyNodeResponse;
import com.teachbase.server.taxonomy.api.TaxonomyVersionResponse;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Applies workspace authorization and lifecycle rules around taxonomy persistence. */
@Service
public class TaxonomyService implements TaxonomyCatalog {

    private final WorkspaceDirectory workspaces;
    private final QuestionRevisionDirectory questions;
    private final TaxonomyRepository taxonomies;
    private final AuditTrail auditTrail;

    public TaxonomyService(
            WorkspaceDirectory workspaces,
            QuestionRevisionDirectory questions,
            TaxonomyRepository taxonomies,
            AuditTrail auditTrail) {
        this.workspaces = workspaces;
        this.questions = questions;
        this.taxonomies = taxonomies;
        this.auditTrail = auditTrail;
    }

    @Transactional
    @Override
    public TaxonomyVersionResponse createVersion(CreateTaxonomyVersionRequest request) {
        validateActor(request.workspaceId(), request.actorUserId());
        int schemaVersion = request.schemaVersion() == 0 ? 1 : request.schemaVersion();
        var result = taxonomies.createVersion(
                request.workspaceId(), request.actorUserId(), clean(request.taxonomyKey()),
                clean(request.versionKey()), clean(request.subject()), clean(request.stage()), schemaVersion);
        audit(request.workspaceId(), request.actorUserId(), "taxonomy_version.created",
                result.taxonomyVersionId(), Map.of("taxonomyKey", result.taxonomyKey(), "versionKey", result.versionKey()));
        return result;
    }

    @Transactional
    @Override
    public TaxonomyNodeResponse createNode(UUID taxonomyVersionId, CreateTaxonomyNodeRequest request) {
        validateActor(request.workspaceId(), request.actorUserId());
        if (!request.metadata().isObject()) throw new TaxonomyValidationException("taxonomy_metadata_invalid");
        var aliases = request.aliases().stream().map(this::clean).distinct().toList();
        var result = taxonomies.createNode(
                request.workspaceId(), request.actorUserId(), taxonomyVersionId, clean(request.knowledgeCode()),
                clean(request.displayName()), request.parentNodeId(), request.sortOrder(), request.metadata(), aliases);
        audit(request.workspaceId(), request.actorUserId(), "taxonomy_node.created",
                result.taxonomyNodeId(), Map.of("taxonomyVersionId", taxonomyVersionId.toString(),
                        "knowledgeCode", result.knowledgeCode()));
        return result;
    }

    @Transactional
    @Override
    public TaxonomyVersionResponse activate(UUID taxonomyVersionId, ActivateTaxonomyVersionRequest request) {
        validateActor(request.workspaceId(), request.actorUserId());
        var result = taxonomies.activate(request.workspaceId(), request.actorUserId(), taxonomyVersionId);
        audit(request.workspaceId(), request.actorUserId(), "taxonomy_version.activated",
                taxonomyVersionId, Map.of("taxonomyKey", result.taxonomyKey(), "versionKey", result.versionKey()));
        return result;
    }

    @Transactional
    @Override
    public QuestionTaxonomyLinkResponse assign(AssignQuestionTaxonomyRequest request) {
        validateActor(request.workspaceId(), request.actorUserId());
        String relation = clean(request.relationType());
        String source = clean(request.assignmentSource());
        if (!Set.of("primary", "secondary").contains(relation)) {
            throw new TaxonomyValidationException("taxonomy_relation_invalid");
        }
        if (!Set.of("human", "model", "import").contains(source)) {
            throw new TaxonomyValidationException("taxonomy_assignment_source_invalid");
        }
        var descriptors = questions.findAll(request.workspaceId(), List.of(request.questionRevisionId()));
        if (descriptors.size() != 1) throw new TaxonomyValidationException("taxonomy_question_revision_not_found");
        var question = descriptors.getFirst();
        var result = taxonomies.assign(
                request.workspaceId(), request.actorUserId(), question.questionId(), question.questionRevisionId(),
                request.taxonomyNodeId(), relation, source, request.confidence());
        audit(request.workspaceId(), request.actorUserId(), "question_taxonomy.assigned",
                result.questionTaxonomyLinkId(), Map.of(
                        "questionRevisionId", question.questionRevisionId().toString(),
                        "taxonomyNodeId", request.taxonomyNodeId().toString(), "relationType", relation));
        return result;
    }

    @Transactional(readOnly = true)
    @Override
    public TaxonomyNodeResponse resolve(ResolveTaxonomyNodeRequest request) {
        validateActor(request.workspaceId(), request.actorUserId());
        return taxonomies.resolve(
                        request.workspaceId(), request.taxonomyVersionId(), clean(request.codeOrAlias()))
                .orElseThrow(() -> new TaxonomyValidationException("taxonomy_node_not_found"));
    }

    private void audit(UUID workspaceId, UUID actorUserId, String type, UUID id, Map<String, Object> payload) {
        auditTrail.record(new AuditCommand(workspaceId, actorUserId, type, "taxonomy", id, payload));
    }

    private void validateActor(UUID workspaceId, UUID actorUserId) {
        if (!workspaces.exists(workspaceId)) throw new WorkspaceNotFoundException();
        if (!workspaces.isActiveMember(workspaceId, actorUserId)) throw new ActorNotWorkspaceMemberException();
    }

    private String clean(String value) {
        return value == null ? "" : value.trim();
    }
}
