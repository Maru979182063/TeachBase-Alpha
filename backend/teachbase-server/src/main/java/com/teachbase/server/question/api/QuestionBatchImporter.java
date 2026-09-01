package com.teachbase.server.question.api;

/** Named module port used by controlled ingestion adapters such as Release Seed. */
public interface QuestionBatchImporter {

    BulkQuestionImportResponse importBatch(BulkQuestionImportRequest request);
}
