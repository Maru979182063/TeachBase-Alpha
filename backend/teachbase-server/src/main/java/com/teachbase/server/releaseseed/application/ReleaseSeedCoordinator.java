package com.teachbase.server.releaseseed.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.Set;
import org.springframework.stereotype.Service;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，负责业务校验和用例编排，不应泄漏数据库记录或传输层对象。
 *
 * 英文术语对照：Runs validate, dry-run, resumable import, and post-import verification modes.
 */
@Service
public class ReleaseSeedCoordinator {

    private final ReleaseSeedPackageValidator validator;
    private final ReleaseSeedItemProcessor items;
    private final ReleaseSeedSourceProcessor sources;
    private final ReleaseSeedRelationProcessor relations;
    private final ReleaseSeedCheckpointService checkpoints;
    private final ObjectMapper objectMapper;

    public ReleaseSeedCoordinator(
            ReleaseSeedPackageValidator validator,
            ReleaseSeedItemProcessor items,
            ReleaseSeedSourceProcessor sources,
            ReleaseSeedRelationProcessor relations,
            ReleaseSeedCheckpointService checkpoints,
            ObjectMapper objectMapper) {
        this.validator = validator;
        this.items = items;
        this.sources = sources;
        this.relations = relations;
        this.checkpoints = checkpoints;
        this.objectMapper = objectMapper;
    }

    public ObjectNode execute(ReleaseSeedProperties properties) {
        String mode = properties.mode() == null ? "" : properties.mode().strip().toLowerCase(java.util.Locale.ROOT);
        if (!Set.of("validate", "dry-run", "import", "verify").contains(mode)) {
            throw new ReleaseSeedValidationException("release_seed_mode_invalid");
        }
        if (properties.packageRoot() == null) throw new ReleaseSeedValidationException("release_seed_package_root_required");
        var seedPackage = validator.validate(properties.packageRoot());
        if (mode.equals("validate")) return baseReport(mode, seedPackage).put("validated", true);
        validateDatabaseOptions(properties);
        if (mode.equals("dry-run")) return dryRun(seedPackage, properties);
        if (mode.equals("verify")) return verify(seedPackage, properties);
        return importPackage(seedPackage, properties);
    }

    private ObjectNode dryRun(ValidatedReleaseSeedPackage seedPackage, ReleaseSeedProperties properties) {
        for (int index = 0; index < seedPackage.questions().size(); index++) {
            items.dryRun(seedPackage, properties, seedPackage.questions().get(index), index);
        }
        return baseReport("dry-run", seedPackage)
                .put("validated", true)
                .put("databaseWrites", 0)
                .put("canonicalHashesVerified", seedPackage.questions().size())
                .put("taxonomyTagsResolved", countTags(seedPackage));
    }

    private ObjectNode importPackage(ValidatedReleaseSeedPackage seedPackage, ReleaseSeedProperties properties) {
        if (properties.storageRoot() == null) throw new ReleaseSeedValidationException("release_seed_storage_root_required");
        ReleaseSeedBatchLease lease = checkpoints.acquire(seedPackage, properties);
        int resumeIndex = lease.nextQuestionIndex();
        if (!lease.completed()) {
            try {
                for (JsonNode sourceDocument : seedPackage.sourceDocuments()) {
                    sources.processDocument(lease, seedPackage, properties, sourceDocument);
                }
                for (JsonNode sourceRegion : seedPackage.sourceRegions()) {
                    sources.processRegion(lease, seedPackage, properties, sourceRegion);
                }
                int processedThisAttempt = 0;
                for (int index = resumeIndex; index < seedPackage.questions().size(); index++) {
                    items.process(lease, seedPackage, properties, seedPackage.questions().get(index), index);
                    processedThisAttempt++;
                    if (properties.effectiveFailAfterItems() > 0
                            && processedThisAttempt >= properties.effectiveFailAfterItems()) {
                        throw new ReleaseSeedInjectedInterruptionException();
                    }
                }
                relations.process(lease, seedPackage, properties);
                lease = checkpoints.complete(lease, seedPackage, properties);
            } catch (ReleaseSeedInjectedInterruptionException exception) {
                // 保留 importing 状态和最后一次已提交游标。后续进程必须等待租约到期，
                // 获取新令牌后再从该游标恢复，不能越过尚未提交的条目。
                throw exception;
            } catch (RuntimeException exception) {
                checkpoints.fail(lease, stableCode(exception));
                throw exception;
            }
        }
        var verification = checkpoints.verify(lease);
        assertComplete(seedPackage, verification);
        ObjectNode report = baseReport("import", seedPackage);
        report.put("releaseSeedBatchId", lease.releaseSeedBatchId().toString());
        report.put("batchStatus", lease.status());
        report.put("attemptNo", lease.attemptNo());
        report.put("resumedFromQuestionIndex", resumeIndex);
        report.put("importedCount", lease.importedCount());
        report.put("reusedCount", lease.reusedCount());
        report.put("approvedCount", lease.approvedCount());
        report.set("verification", verificationNode(verification));
        return report;
    }

    private ObjectNode verify(ValidatedReleaseSeedPackage seedPackage, ReleaseSeedProperties properties) {
        var lease = checkpoints.find(seedPackage, properties);
        if (!lease.completed()) throw new ReleaseSeedValidationException("release_seed_batch_not_completed");
        var verification = checkpoints.verify(lease);
        assertComplete(seedPackage, verification);
        ObjectNode report = baseReport("verify", seedPackage);
        report.put("releaseSeedBatchId", lease.releaseSeedBatchId().toString());
        report.put("batchStatus", lease.status());
        report.put("attemptNo", lease.attemptNo());
        report.set("verification", verificationNode(verification));
        return report;
    }

    private void validateDatabaseOptions(ReleaseSeedProperties properties) {
        if (properties.workspaceId() == null) throw new ReleaseSeedValidationException("release_seed_workspace_required");
        if (properties.actorUserId() == null) throw new ReleaseSeedValidationException("release_seed_actor_required");
        if (properties.taxonomyVersionId() == null) {
            throw new ReleaseSeedValidationException("release_seed_taxonomy_version_required");
        }
        if (blank(properties.defaultSubject())) throw new ReleaseSeedValidationException("release_seed_subject_required");
        if (blank(properties.defaultQuestionType())) {
            throw new ReleaseSeedValidationException("release_seed_question_type_required");
        }
    }

    private void assertComplete(
            ValidatedReleaseSeedPackage seedPackage,
            ReleaseSeedVerification verification) {
        if (verification.itemCount() != seedPackage.questions().size()
                || verification.approvedItemCount() != seedPackage.questions().size()
                || verification.questionRevisionCount() != seedPackage.questions().size()
                || verification.taxonomyLinkCount() < seedPackage.questions().size()
                || verification.sourceDocumentCount() != seedPackage.sourceDocuments().size()
                || verification.sourceRegionCount() != seedPackage.sourceRegions().size()
                || verification.relationCount() != seedPackage.relations().size()) {
            throw new ReleaseSeedValidationException("release_seed_post_import_verification_failed");
        }
    }

    private ObjectNode baseReport(String mode, ValidatedReleaseSeedPackage seedPackage) {
        ObjectNode report = objectMapper.createObjectNode();
        report.put("schemaVersion", "teachbase.release-seed.loader-report.v1");
        report.put("generatedAt", java.time.OffsetDateTime.now().toString());
        report.put("status", "passed");
        report.put("mode", mode);
        report.put("batchId", seedPackage.batchId());
        report.put("releaseVersion", seedPackage.releaseVersion());
        report.put("packageContentSha256", seedPackage.packageContentHash());
        report.put("questionCount", seedPackage.questions().size());
        report.put("rejectedQuestionCount", seedPackage.rejectedQuestions().size());
        report.put("reportUsesAbsolutePathsAsInputContract", false);
        return report;
    }

    private ObjectNode verificationNode(ReleaseSeedVerification value) {
        ObjectNode node = objectMapper.createObjectNode();
        node.put("itemCount", value.itemCount());
        node.put("approvedItemCount", value.approvedItemCount());
        node.put("questionRevisionCount", value.questionRevisionCount());
        node.put("reviewDecisionCount", value.reviewDecisionCount());
        node.put("sourceDocumentCount", value.sourceDocumentCount());
        node.put("sourceRegionCount", value.sourceRegionCount());
        node.put("relationCount", value.relationCount());
        node.put("taxonomyLinkCount", value.taxonomyLinkCount());
        return node;
    }

    private int countTags(ValidatedReleaseSeedPackage seedPackage) {
        int count = 0;
        for (JsonNode question : seedPackage.questions()) {
            count += 1 + question.path("secondaryKnowledgeTags").size();
        }
        return count;
    }

    private String stableCode(RuntimeException exception) {
        String message = exception.getMessage();
        return message != null && message.matches("[a-z0-9_:-]+") ? message : "release_seed_import_failed";
    }

    private boolean blank(String value) {
        return value == null || value.isBlank();
    }
}
