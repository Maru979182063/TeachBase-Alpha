package com.teachbase.server.question.api;

/** Read-only canonical hashing port used by dry-run ingestion validation. */
public interface QuestionHashPreviewer {

    QuestionHashPreview previewHashes(QuestionImportItem item);
}
