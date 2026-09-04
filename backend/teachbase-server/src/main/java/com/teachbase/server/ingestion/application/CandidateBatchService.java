package com.teachbase.server.ingestion.application;

import com.teachbase.server.fileasset.api.FileVersionEvidence;
import com.teachbase.server.ingestion.api.CandidateBatchRequest;
import com.teachbase.server.ingestion.api.CandidateBatchResponse;
import com.teachbase.server.question.api.BulkQuestionImportRequest;
import com.teachbase.server.question.api.QuestionBatchImporter;
import com.teachbase.server.question.api.QuestionIngestionLinker;
import com.teachbase.server.question.api.QuestionSourceEvidenceCommand;
import com.teachbase.server.review.api.OpenReviewCaseRequest;
import com.teachbase.server.review.api.ReviewCaseResponse;
import com.teachbase.server.review.api.ReviewWorkflow;
import com.teachbase.server.source.api.RegisterSourceDocumentCommand;
import com.teachbase.server.source.api.RegisterSourceRegionCommand;
import com.teachbase.server.source.api.SourceCatalog;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 中文维护说明：单事务编排候选保存，不绕过题目模块的成员、哈希和待审核状态校验。
 * 任一题、来源关联或审核任务失败均回滚整批；文件字节由调用方预先持久化，失败后可重试。
 */
@Service
public class CandidateBatchService {
    private final QuestionBatchImporter questions;
    private final QuestionIngestionLinker links;
    private final SourceCatalog sources;
    private final ReviewWorkflow reviews;
    private final FileVersionEvidence files;

    public CandidateBatchService(QuestionBatchImporter questions, QuestionIngestionLinker links,
            SourceCatalog sources, ReviewWorkflow reviews, FileVersionEvidence files) {
        this.questions = questions;
        this.links = links;
        this.sources = sources;
        this.reviews = reviews;
        this.files = files;
    }

    @Transactional
    public CandidateBatchResponse ingest(CandidateBatchRequest request) {
        // 来源键采用显式文档前缀，不推断题目语义或跨文档相似性。
        String prefix = request.sourceSha256() + "/";
        Set<List<String>> identities = new HashSet<>();
        for (var item : request.questions()) {
            if (!item.sourceKey().startsWith(prefix)
                    || !identities.add(List.of(item.sourceSystem(), item.sourceKey()))) {
                throw new CandidateValidationException("candidate_source_identity_invalid");
            }
        }
        var imported = questions.importBatch(new BulkQuestionImportRequest(
                request.workspaceId(), request.actorUserId(), request.questions()));
        if (!files.matches(request.workspaceId(), request.sourceFileVersionId(), request.sourceSha256())) {
            throw new CandidateValidationException("candidate_source_file_mismatch");
        }
        if (!request.sourceMetadata().isObject()) {
            throw new CandidateValidationException("candidate_source_metadata_invalid");
        }
        var source = sources.registerDocument(new RegisterSourceDocumentCommand(
                request.workspaceId(), request.actorUserId(), request.sourceFileVersionId(),
                request.sourceSha256(), request.sourceType(), request.subject(), "", "", request.title(),
                request.sourceMetadata()));
        List<CandidateBatchResponse.Item> results = new ArrayList<>();
        for (int i = 0; i < imported.results().size(); i++) {
            var result = imported.results().get(i);
            var input = request.questions().get(i);
            var region = sources.registerRegion(new RegisterSourceRegionCommand(
                    request.workspaceId(), request.actorUserId(), source.id(),
                    result.questionRevisionId().toString(), "question", null, null, null,
                    input.stemMarkdown(), input.provenance()));
            links.linkSource(new QuestionSourceEvidenceCommand(
                    request.workspaceId(), result.questionId(), result.questionRevisionId(),
                    source.id(), region.id(), request.title(), null, null, input.provenance()));
            ReviewCaseResponse review = null;
            if (Set.of("unreviewed", "pending_review").contains(result.reviewStatus())) {
                review = reviews.open(new OpenReviewCaseRequest(
                        request.workspaceId(), request.actorUserId(), result.questionRevisionId(), null));
            }
            results.add(new CandidateBatchResponse.Item(result, region.id(), review));
        }
        return new CandidateBatchResponse(source.id(), List.copyOf(results));
    }
}
