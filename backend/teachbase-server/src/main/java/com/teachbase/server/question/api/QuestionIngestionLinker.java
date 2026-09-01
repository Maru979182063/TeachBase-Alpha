package com.teachbase.server.question.api;

/** Named ingestion port for source evidence and question graph relationships. */
public interface QuestionIngestionLinker {

    void linkSource(QuestionSourceEvidenceCommand command);

    void linkRelation(QuestionRelationCommand command);
}
