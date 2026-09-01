package com.teachbase.server.releaseseed.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.question.api.BulkQuestionImportRequest;
import com.teachbase.server.question.api.QuestionBatchImporter;
import com.teachbase.server.question.api.QuestionHashPreviewer;
import com.teachbase.server.question.api.QuestionIngestionLinker;
import com.teachbase.server.question.api.QuestionSourceEvidenceCommand;
import com.teachbase.server.review.api.DecideReviewCaseRequest;
import com.teachbase.server.review.api.OpenReviewCaseRequest;
import com.teachbase.server.review.api.ReviewWorkflow;
import com.teachbase.server.taxonomy.api.AssignQuestionTaxonomyRequest;
import com.teachbase.server.taxonomy.api.ResolveTaxonomyNodeRequest;
import com.teachbase.server.taxonomy.api.TaxonomyCatalog;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * 中文维护说明：本文件属于首发数据包导入模块的业务规则与事务编排层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Imports, reviews, classifies, links, and checkpoints one question atomically.
 */
@Service
public class ReleaseSeedItemProcessor {

    private final ReleaseSeedQuestionMapper mapper;
    private final QuestionHashPreviewer hashes;
    private final QuestionBatchImporter questions;
    private final ReviewWorkflow reviews;
    private final TaxonomyCatalog taxonomies;
    private final QuestionIngestionLinker links;
    private final ReleaseSeedRepository checkpoints;
    private final ReleaseSeedAssetPublisher assets;
    private final ObjectMapper objectMapper;

    public ReleaseSeedItemProcessor(
            ReleaseSeedQuestionMapper mapper,
            QuestionHashPreviewer hashes,
            QuestionBatchImporter questions,
            ReviewWorkflow reviews,
            TaxonomyCatalog taxonomies,
            QuestionIngestionLinker links,
            ReleaseSeedRepository checkpoints,
            ReleaseSeedAssetPublisher assets,
            ObjectMapper objectMapper) {
        this.mapper = mapper;
        this.hashes = hashes;
        this.questions = questions;
        this.reviews = reviews;
        this.taxonomies = taxonomies;
        this.links = links;
        this.checkpoints = checkpoints;
        this.assets = assets;
        this.objectMapper = objectMapper;
    }

    public void dryRun(
            ValidatedReleaseSeedPackage seedPackage,
            ReleaseSeedProperties properties,
            JsonNode row,
            int itemIndex) {
        var item = mapper.map(seedPackage, properties, row, itemIndex);
        hashes.previewHashes(item);
        resolveTags(properties, row);
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public ReleaseSeedItemResult process(
            ReleaseSeedBatchLease lease,
            ValidatedReleaseSeedPackage seedPackage,
            ReleaseSeedProperties properties,
            JsonNode row,
            int itemIndex) {
        checkpoints.heartbeat(lease.releaseSeedBatchId(), lease.workerToken(), properties.effectiveLeaseDuration());
        publishQuestionImages(seedPackage, properties, row);
        var item = mapper.map(seedPackage, properties, row, itemIndex);
        hashes.previewHashes(item);
        var resolvedTags = resolveTags(properties, row);
        var imported = questions.importBatch(new BulkQuestionImportRequest(
                properties.workspaceId(), properties.actorUserId(), List.of(item))).results().getFirst();

        UUID reviewCaseId = null;
        if (imported.reviewStatus().equals("approved")) {
            // 不同的已校验数据包可能包含字节完全相同的来源题目。
            // 此时复用既有已审核修订，不伪造第二次人工结论；
            // 但仍记录本数据包的导入观察信封，保证来源可追溯。
            if (imported.createdRevision()) {
                throw new ReleaseSeedValidationException("release_seed_created_revision_already_approved");
            }
        } else {
            if (!java.util.Set.of("unreviewed", "pending_review").contains(imported.reviewStatus())) {
                throw new ReleaseSeedValidationException("release_seed_existing_revision_not_approvable");
            }
            var opened = reviews.open(new OpenReviewCaseRequest(
                    properties.workspaceId(), properties.actorUserId(), imported.questionRevisionId(),
                    properties.actorUserId()));
            reviewCaseId = opened.reviewCaseId();
            JsonNode humanReview = row.path("review");
            var evidence = objectMapper.createObjectNode();
            evidence.put("batchId", seedPackage.batchId());
            evidence.put("releaseVersion", seedPackage.releaseVersion());
            evidence.put("packageContentSha256", seedPackage.packageContentHash());
            evidence.put("externalReviewerId", humanReview.path("reviewerId").asText());
            evidence.set("validationReport", seedPackage.validationReport().deepCopy());
            evidence.set("reviewReport", seedPackage.reviewReport().deepCopy());
            reviews.decide(opened.reviewCaseId(), new DecideReviewCaseRequest(
                    properties.workspaceId(), properties.actorUserId(), opened.expectedContentHash(), "approved",
                    "Approved by validated Release Seed package", humanReview.path("reviewPolicyVersion").asText(),
                    "release_seed", evidence, OffsetDateTime.parse(humanReview.path("reviewedAt").asText())));
        }

        assignTags(properties, imported.questionRevisionId(), row, resolvedTags);
        linkSource(lease.releaseSeedBatchId(), properties, imported.questionId(), imported.questionRevisionId(), row);
        var result = new ReleaseSeedItemResult(
                imported.questionId(), imported.questionRevisionId(), reviewCaseId,
                imported.createdQuestion(), imported.createdRevision());
        checkpoints.recordApproved(
                lease.releaseSeedBatchId(), lease.workerToken(), itemIndex, result,
                properties.effectiveLeaseDuration());
        return result;
    }

    private List<com.teachbase.server.taxonomy.api.TaxonomyNodeResponse> resolveTags(
            ReleaseSeedProperties properties,
            JsonNode row) {
        var resolved = new java.util.ArrayList<com.teachbase.server.taxonomy.api.TaxonomyNodeResponse>();
        resolved.add(taxonomies.resolve(new ResolveTaxonomyNodeRequest(
                properties.workspaceId(), properties.actorUserId(), properties.taxonomyVersionId(),
                row.path("primaryKnowledgeTag").asText())));
        for (JsonNode tag : row.path("secondaryKnowledgeTags")) {
            resolved.add(taxonomies.resolve(new ResolveTaxonomyNodeRequest(
                    properties.workspaceId(), properties.actorUserId(), properties.taxonomyVersionId(), tag.asText())));
        }
        return List.copyOf(resolved);
    }

    private void assignTags(
            ReleaseSeedProperties properties,
            UUID questionRevisionId,
            JsonNode row,
            List<com.teachbase.server.taxonomy.api.TaxonomyNodeResponse> resolved) {
        BigDecimal confidence = row.path("tagging").path("confidence").isNumber()
                ? row.path("tagging").path("confidence").decimalValue() : null;
        Set<UUID> assigned = new HashSet<>();
        for (int index = 0; index < resolved.size(); index++) {
            var node = resolved.get(index);
            if (!assigned.add(node.taxonomyNodeId())) continue;
            taxonomies.assign(new AssignQuestionTaxonomyRequest(
                    properties.workspaceId(), properties.actorUserId(), questionRevisionId,
                    node.taxonomyNodeId(), index == 0 ? "primary" : "secondary", "import", confidence));
        }
    }

    private void linkSource(
            UUID batchId,
            ReleaseSeedProperties properties,
            UUID questionId,
            UUID questionRevisionId,
            JsonNode row) {
        String documentKey = row.path("sourceDocumentKey").asText("");
        String regionKey = row.path("sourceRegionKey").asText("");
        if (documentKey.isBlank() && regionKey.isBlank()) return;
        var document = documentKey.isBlank() ? null : checkpoints.findSourceDocument(batchId, documentKey)
                .orElseThrow(() -> new ReleaseSeedValidationException("release_seed_question_document_map_missing"));
        var region = regionKey.isBlank() ? null : checkpoints.findSourceRegion(batchId, regionKey)
                .orElseThrow(() -> new ReleaseSeedValidationException("release_seed_question_region_map_missing"));
        JsonNode locator = row.path("sourceLocator");
        Integer page = locator.path("page").isIntegralNumber() ? locator.path("page").asInt() : null;
        links.linkSource(new QuestionSourceEvidenceCommand(
                properties.workspaceId(), questionId, questionRevisionId,
                document == null ? null : document.sourceDocumentId(),
                region == null ? null : region.sourceRegionId(),
                row.path("sourceSystem").asText() + ":" + row.path("sourceKey").asText(),
                page, page, locator.deepCopy()));
    }

    private void publishQuestionImages(
            ValidatedReleaseSeedPackage seedPackage,
            ReleaseSeedProperties properties,
            JsonNode row) {
        for (JsonNode image : row.path("original").path("imageRefs")) {
            assets.publish(
                    properties.workspaceId(), properties.actorUserId(), seedPackage.root(), properties.storageRoot(),
                    seedPackage.packageContentHash(), image.path("path").asText(),
                    image.path("mediaType").asText("application/octet-stream"), image.path("sha256").asText());
        }
    }
}
