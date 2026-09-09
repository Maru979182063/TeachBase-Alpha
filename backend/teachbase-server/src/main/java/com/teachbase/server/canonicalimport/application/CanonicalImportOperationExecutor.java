package com.teachbase.server.canonicalimport.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.teachbase.server.editor.api.EditorImportCommand;
import com.teachbase.server.editor.api.EditorImportGateway;
import com.teachbase.server.fileasset.api.FileVersionDirectory;
import com.teachbase.server.handout.api.CreateHandoutCompositionRequest;
import com.teachbase.server.handout.api.EditorRevisionArtifactInput;
import com.teachbase.server.handout.api.HandoutCompositionImporter;
import com.teachbase.server.handout.api.HandoutEditionInput;
import com.teachbase.server.handout.api.HandoutOccurrenceInput;
import com.teachbase.server.handout.api.HandoutOccurrenceSourceInput;
import com.teachbase.server.question.api.BulkQuestionImportRequest;
import com.teachbase.server.question.api.QuestionBatchImporter;
import com.teachbase.server.question.api.QuestionIngestionLinker;
import com.teachbase.server.question.api.QuestionSourceEvidenceCommand;
import com.teachbase.server.review.api.OpenReviewCaseRequest;
import com.teachbase.server.review.api.OpenStandardModuleReviewCaseRequest;
import com.teachbase.server.review.api.ReviewWorkflow;
import com.teachbase.server.source.api.RegisterSourceDocumentCommand;
import com.teachbase.server.source.api.RegisterSourceRegionCommand;
import com.teachbase.server.source.api.SourceCatalog;
import com.teachbase.server.standardmodule.api.CreateStandardModuleRequest;
import com.teachbase.server.standardmodule.api.LinkStandardModuleFileRequest;
import com.teachbase.server.standardmodule.api.LinkStandardModuleSourceRequest;
import com.teachbase.server.standardmodule.api.StandardModuleImporter;
import com.teachbase.server.taxonomy.api.AssignQuestionTaxonomyRequest;
import com.teachbase.server.taxonomy.api.AssignStandardModuleTaxonomyRequest;
import com.teachbase.server.taxonomy.api.ResolveTaxonomyNodeRequest;
import com.teachbase.server.taxonomy.api.TaxonomyCatalog;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Component;

/**
 * 中文维护说明：把冻结 operation 映射到各领域公开端口；这里不直接写任何领域表，
 * 因而现有哈希、审核、租户隔离与不可变 revision 规则不会被导入器旁路。
 */
@Component
class CanonicalImportOperationExecutor {

    private final ObjectMapper mapper;
    private final FileVersionDirectory files;
    private final SourceCatalog sources;
    private final QuestionBatchImporter questions;
    private final QuestionIngestionLinker questionLinks;
    private final StandardModuleImporter modules;
    private final TaxonomyCatalog taxonomy;
    private final ReviewWorkflow reviews;
    private final EditorImportGateway editors;
    private final HandoutCompositionImporter handouts;

    CanonicalImportOperationExecutor(
            ObjectMapper mapper, FileVersionDirectory files, SourceCatalog sources,
            QuestionBatchImporter questions, QuestionIngestionLinker questionLinks,
            StandardModuleImporter modules, TaxonomyCatalog taxonomy, ReviewWorkflow reviews,
            EditorImportGateway editors, HandoutCompositionImporter handouts) {
        this.mapper = mapper;
        this.files = files;
        this.sources = sources;
        this.questions = questions;
        this.questionLinks = questionLinks;
        this.modules = modules;
        this.taxonomy = taxonomy;
        this.reviews = reviews;
        this.editors = editors;
        this.handouts = handouts;
    }

    ImportOperationOutcome execute(
            UUID workspaceId, UUID actorUserId, ImportOperationRecord operation,
            Map<String, ImportOperationRecord> completed) {
        JsonNode p = operation.payload();
        return switch (operation.operationType()) {
            case "file_reference" -> file(workspaceId, p);
            case "source_document" -> sourceDocument(workspaceId, actorUserId, p, completed);
            case "source_region" -> sourceRegion(workspaceId, actorUserId, p, completed);
            case "question_revision" -> question(workspaceId, actorUserId, p);
            case "question_provenance" -> questionSource(workspaceId, p, completed);
            case "standard_module_revision" -> module(workspaceId, actorUserId, p);
            case "standard_module_provenance" -> moduleSource(workspaceId, actorUserId, p, completed);
            case "standard_module_file" -> moduleFile(workspaceId, actorUserId, p, completed);
            case "taxonomy_assignment" -> taxonomy(workspaceId, actorUserId, p, completed);
            case "review_intent" -> review(workspaceId, actorUserId, p, completed);
            case "editor_revision" -> editor(workspaceId, actorUserId, p);
            case "handout_composition" -> handout(workspaceId, actorUserId, p, completed);
            default -> throw new CanonicalImportValidationException("canonical_import_operation_type_unknown");
        };
    }

    private ImportOperationOutcome file(UUID workspaceId, JsonNode p) {
        UUID id = uuid(p, "fileVersionId");
        var found = files.findAll(workspaceId, List.of(id));
        if (found.size() != 1 || !found.getFirst().sha256().equals(text(p, "sha256"))) {
            throw new CanonicalImportValidationException("canonical_import_file_changed_after_validation");
        }
        return outcome(id, null, found.getFirst().sha256(), Map.of("fileVersionId", id));
    }

    private ImportOperationOutcome sourceDocument(
            UUID workspaceId, UUID actorUserId, JsonNode p, Map<String, ImportOperationRecord> done) {
        UUID fileId = target(done, "file:" + text(p, "fileKey"));
        var result = sources.registerDocument(new RegisterSourceDocumentCommand(
                workspaceId, actorUserId, fileId, text(p, "externalSourceKey"), text(p, "sourceType"),
                text(p, "subject"), optional(p, "stage"), optional(p, "grade"), text(p, "title"), object(p, "metadata")));
        return outcome(result.id(), null, null, Map.of("sourceDocumentId", result.id(), "created", result.created()));
    }

    private ImportOperationOutcome sourceRegion(
            UUID workspaceId, UUID actorUserId, JsonNode p, Map<String, ImportOperationRecord> done) {
        UUID documentId = target(done, "source-document:" + text(p, "sourceDocumentKey"));
        var result = sources.registerRegion(new RegisterSourceRegionCommand(
                workspaceId, actorUserId, documentId, text(p, "sourceRegionKey"), text(p, "regionType"),
                integer(p, "pageNo"), integer(p, "orderIndex"), nullableObject(p, "boundingBox"),
                optional(p, "extractedText"), object(p, "sourceReference")));
        return outcome(result.id(), null, null, Map.of("sourceRegionId", result.id(), "created", result.created()));
    }

    private ImportOperationOutcome question(UUID workspaceId, UUID actorUserId, JsonNode p) {
        var response = questions.importBatch(new BulkQuestionImportRequest(
                workspaceId, actorUserId, List.of(CanonicalImportPayloadMapper.question(p))));
        var result = response.results().getFirst();
        return outcome(result.questionId(), result.questionRevisionId(), null, Map.of(
                "questionId", result.questionId(), "questionRevisionId", result.questionRevisionId(),
                "revisionNo", result.revisionNo(), "createdQuestion", result.createdQuestion(),
                "createdRevision", result.createdRevision()));
    }

    private ImportOperationOutcome questionSource(
            UUID workspaceId, JsonNode p, Map<String, ImportOperationRecord> done) {
        var question = require(done, "question:" + text(p, "questionKey"));
        UUID documentId = target(done, "source-document:" + text(p, "sourceDocumentKey"));
        UUID regionId = optionalTarget(done, "source-region:", p, "sourceRegionKey");
        questionLinks.linkSource(new QuestionSourceEvidenceCommand(
                workspaceId, question.targetId(), question.targetRevisionId(), text(p, "evidenceKey"),
                documentId, regionId, optional(p, "sourceLabel"), integer(p, "pageStart"),
                integer(p, "pageEnd"), object(p, "sourceReference")));
        return outcome(question.targetId(), question.targetRevisionId(), question.targetHash(),
                Map.of("sourceEvidenceKey", text(p, "evidenceKey")));
    }

    private ImportOperationOutcome module(UUID workspaceId, UUID actorUserId, JsonNode p) {
        var result = modules.importModule(new CreateStandardModuleRequest(
                workspaceId, actorUserId, text(p, "moduleKey"), text(p, "moduleType"), text(p, "title"),
                text(p, "subject"), optional(p, "stage"), optional(p, "grade"),
                p.path("schemaVersion").asInt(), object(p, "content")));
        return outcome(result.standardModuleId(), result.standardModuleRevisionId(), result.contentHash(), Map.of(
                "standardModuleId", result.standardModuleId(),
                "standardModuleRevisionId", result.standardModuleRevisionId(),
                "revisionNo", result.revisionNo(), "createdModule", result.createdModule(),
                "createdRevision", result.createdRevision()));
    }

    private ImportOperationOutcome moduleSource(
            UUID workspaceId, UUID actorUserId, JsonNode p, Map<String, ImportOperationRecord> done) {
        var module = require(done, "module:" + text(p, "moduleKey"));
        UUID documentId = target(done, "source-document:" + text(p, "sourceDocumentKey"));
        UUID regionId = optionalTarget(done, "source-region:", p, "sourceRegionKey");
        var result = modules.importSource(module.targetRevisionId(), new LinkStandardModuleSourceRequest(
                workspaceId, actorUserId, text(p, "evidenceKey"), documentId, regionId,
                optionalOr(p, "sourceRole", "canonical"), object(p, "sourceReference")));
        return outcome(result.linkId(), module.targetRevisionId(), null, Map.of("created", result.created()));
    }

    private ImportOperationOutcome moduleFile(
            UUID workspaceId, UUID actorUserId, JsonNode p, Map<String, ImportOperationRecord> done) {
        var module = require(done, "module:" + text(p, "moduleKey"));
        UUID fileId = target(done, "file:" + text(p, "fileKey"));
        var result = modules.importFile(module.targetRevisionId(), new LinkStandardModuleFileRequest(
                workspaceId, actorUserId, fileId, text(p, "referenceKey"), text(p, "referenceRole"),
                object(p, "metadata")));
        return outcome(result.linkId(), module.targetRevisionId(), null, Map.of("created", result.created()));
    }

    private ImportOperationOutcome taxonomy(
            UUID workspaceId, UUID actorUserId, JsonNode p, Map<String, ImportOperationRecord> done) {
        var node = taxonomy.resolve(new ResolveTaxonomyNodeRequest(
                workspaceId, actorUserId, uuid(p, "taxonomyVersionId"), text(p, "codeOrAlias")));
        String type = text(p, "targetType");
        var asset = require(done, (type.equals("question") ? "question:" : "module:") + text(p, "targetKey"));
        BigDecimal confidence = p.path("confidence").isNumber() ? p.path("confidence").decimalValue() : null;
        if (type.equals("question")) {
            var result = taxonomy.assign(new AssignQuestionTaxonomyRequest(
                    workspaceId, actorUserId, asset.targetRevisionId(), node.taxonomyNodeId(),
                    text(p, "relationType"), text(p, "assignmentSource"), confidence));
            return outcome(result.questionTaxonomyLinkId(), asset.targetRevisionId(), null, Map.of("taxonomyNodeId", node.taxonomyNodeId()));
        }
        var result = taxonomy.assignStandardModule(new AssignStandardModuleTaxonomyRequest(
                workspaceId, actorUserId, asset.targetRevisionId(), node.taxonomyNodeId(),
                text(p, "relationType"), text(p, "assignmentSource"), confidence));
        return outcome(result.standardModuleTaxonomyLinkId(), asset.targetRevisionId(), null, Map.of("taxonomyNodeId", node.taxonomyNodeId()));
    }

    private ImportOperationOutcome review(
            UUID workspaceId, UUID actorUserId, JsonNode p, Map<String, ImportOperationRecord> done) {
        String type = text(p, "targetType");
        var asset = require(done, (type.equals("question") ? "question:" : "module:") + text(p, "targetKey"));
        UUID assignedTo = nullableUuid(p, "assignedTo");
        var result = type.equals("question")
                ? reviews.open(new OpenReviewCaseRequest(workspaceId, actorUserId, asset.targetRevisionId(), assignedTo))
                : reviews.openStandardModule(new OpenStandardModuleReviewCaseRequest(
                        workspaceId, actorUserId, asset.targetRevisionId(), assignedTo));
        return outcome(result.reviewCaseId(), asset.targetRevisionId(), result.expectedContentHash(),
                Map.of("status", result.status(), "targetType", result.targetType()));
    }

    private ImportOperationOutcome editor(UUID workspaceId, UUID actorUserId, JsonNode p) {
        var result = editors.importFrozenRevision(new EditorImportCommand(
                workspaceId, actorUserId, text(p, "editorDocumentKey"),
                optionalOr(p, "documentKind", "handout"), text(p, "title"),
                p.path("schemaVersion").asInt(), object(p, "masterDoc"), array(p, "versionOverrides")));
        return outcome(result.editorDocumentId(), result.editorRevisionId(), result.contentHash(), Map.of(
                "editorDocumentId", result.editorDocumentId(), "editorRevisionId", result.editorRevisionId(),
                "revisionNo", result.revisionNo(), "createdDocument", result.createdDocument(),
                "createdRevision", result.createdRevision()));
    }

    private ImportOperationOutcome handout(
            UUID workspaceId, UUID actorUserId, JsonNode p, Map<String, ImportOperationRecord> done) {
        var editor = require(done, "editor:" + text(p, "editorDocumentKey"));
        List<HandoutEditionInput> editions = new ArrayList<>();
        for (JsonNode edition : array(p, "editions")) {
            List<HandoutOccurrenceInput> occurrences = new ArrayList<>();
            for (JsonNode occurrence : array(edition, "occurrences")) {
                String kind = text(occurrence, "kind");
                UUID questionRevision = kind.equals("question")
                        ? require(done, "question:" + text(occurrence, "questionKey")).targetRevisionId() : null;
                UUID moduleRevision = kind.equals("standard_module")
                        ? require(done, "module:" + text(occurrence, "moduleKey")).targetRevisionId() : null;
                List<HandoutOccurrenceSourceInput> occurrenceSources = new ArrayList<>();
                for (JsonNode source : optionalArray(occurrence, "sources")) {
                    occurrenceSources.add(new HandoutOccurrenceSourceInput(
                            text(source, "evidenceKey"),
                            target(done, "source-document:" + text(source, "sourceDocumentKey")),
                            optionalTarget(done, "source-region:", source, "sourceRegionKey"),
                            optionalOr(source, "sourceRole", "placement"), object(source, "sourceReference")));
                }
                occurrences.add(new HandoutOccurrenceInput(
                        text(occurrence, "occurrenceKey"), optional(occurrence, "parentOccurrenceKey"),
                        occurrence.path("positionIndex").asInt(), kind, questionRevision, moduleRevision,
                        kind.equals("ordinary_content") ? object(occurrence, "localContent") : null,
                        object(occurrence, "attributes"), occurrenceSources));
            }
            editions.add(new HandoutEditionInput(
                    text(edition, "editionKey"), text(edition, "editionRole"),
                    optional(edition, "canonicalTeacherEditionKey"), edition.path("schemaVersion").asInt(),
                    object(edition, "projectionRules"), object(edition, "delta"), occurrences));
        }
        List<EditorRevisionArtifactInput> artifacts = new ArrayList<>();
        for (JsonNode artifact : array(p, "artifacts")) {
            String sourceKey = optional(artifact, "sourceDocumentKey");
            artifacts.add(new EditorRevisionArtifactInput(
                    text(artifact, "artifactKey"), text(artifact, "artifactRole"),
                    target(done, "file:" + text(artifact, "fileKey")),
                    sourceKey == null ? null : target(done, "source-document:" + sourceKey),
                    object(artifact, "metadata")));
        }
        var result = handouts.importComposition(editor.targetId(), editor.targetRevisionId(),
                new CreateHandoutCompositionRequest(workspaceId, actorUserId, editions, artifacts));
        return outcome(editor.targetId(), editor.targetRevisionId(), editor.targetHash(), Map.of(
                "editionCount", result.editions().size(), "artifactCount", result.artifactCount()));
    }

    private ImportOperationOutcome outcome(UUID id, UUID revisionId, String hash, Map<String, ?> values) {
        return new ImportOperationOutcome(id, revisionId, hash, mapper.valueToTree(values));
    }

    private ImportOperationRecord require(Map<String, ImportOperationRecord> done, String key) {
        ImportOperationRecord result = done.get(key);
        if (result == null || !"completed".equals(result.status())) {
            throw new CanonicalImportConflictException("canonical_import_dependency_not_completed:" + key);
        }
        return result;
    }

    private UUID target(Map<String, ImportOperationRecord> done, String key) {
        UUID result = require(done, key).targetId();
        if (result == null) throw new CanonicalImportConflictException("canonical_import_dependency_target_missing:" + key);
        return result;
    }

    private UUID optionalTarget(Map<String, ImportOperationRecord> done, String prefix, JsonNode p, String field) {
        String key = optional(p, field);
        return key == null ? null : target(done, prefix + key);
    }

    private JsonNode object(JsonNode p, String field) {
        JsonNode value = p.get(field);
        if (value == null || !value.isObject()) throw new CanonicalImportValidationException("canonical_import_object_required:" + field);
        return value;
    }

    private JsonNode array(JsonNode p, String field) {
        JsonNode value = p.get(field);
        if (value == null || !value.isArray()) throw new CanonicalImportValidationException("canonical_import_array_required:" + field);
        return value;
    }

    private Iterable<JsonNode> optionalArray(JsonNode p, String field) {
        JsonNode value = p.get(field);
        return value == null || value.isNull() ? List.of() : value;
    }

    private String text(JsonNode p, String field) {
        String value = p.path(field).asText("").trim();
        if (value.isEmpty()) throw new CanonicalImportValidationException("canonical_import_field_required:" + field);
        return value;
    }

    private String optional(JsonNode p, String field) {
        String value = p.path(field).asText("").trim();
        return value.isEmpty() ? null : value;
    }

    private String optionalOr(JsonNode p, String field, String fallback) {
        String value = optional(p, field);
        return value == null ? fallback : value;
    }

    private Integer integer(JsonNode p, String field) {
        return p.path(field).isIntegralNumber() ? p.path(field).intValue() : null;
    }

    private UUID uuid(JsonNode p, String field) {
        return UUID.fromString(text(p, field));
    }

    private UUID nullableUuid(JsonNode p, String field) {
        String value = optional(p, field);
        return value == null ? null : UUID.fromString(value);
    }

    private JsonNode nullableObject(JsonNode p, String field) {
        JsonNode value = p.get(field);
        return value == null || value.isNull() ? null : value;
    }
}
