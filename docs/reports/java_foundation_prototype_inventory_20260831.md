# Java Foundation Prototype Contract Inventory

- Prototype schema: `alpha-build-fixtures-v2`
- Effective questions: **85**
- Handout drafts: **2**
- Handout snapshots: **6**
- Editor model: `master-overrides-v1`
- Prototype tests discovered: **5**

The source directory is supplied at execution time. No machine-specific absolute path is stored in this report.

## Entity Contracts

| Fixture entity | Records | Fields |
|---|---:|---|
| `baskets` | 2 | `basketId`, `courseNodeId`, `isDirty`, `items`, `knowledgePointId`, `lectureId`, `savedRevision`, `status` |
| `publishedBasketSnapshots` | 2 | `basketId`, `basketSnapshotId`, `itemIds`, `items`, `publishedAt`, `sourceRevision` |
| `normalizedHandouts` | 2 | `blockOrder`, `blocks`, `courseNodeId`, `grade`, `handoutId`, `lectureId`, `mappingStatus`, `mappingType`, `moduleId`, `readiness`, `source`, `stage`, `subject`, `term`, `title` |
| `handoutDrafts` | 2 | `activeVersionId`, `basketSnapshotId`, `contentRevision`, `courseNodeId`, `handoutDraftId`, `handoutId`, `knowledgePointId`, `knowledgeVersionId`, `lectureId`, `questionAssignments`, `returnRecords`, `status`, `versions` |
| `previewConfirmations` | 6 | `blockOrder`, `confirmationId`, `confirmedAt`, `contentRevision`, `handoutDraftId`, `handoutVersionId` |
| `handoutSnapshots` | 6 | `audienceCapabilities`, `blockOrder`, `confirmationId`, `contentRevision`, `courseNodeId`, `createdAt`, `frozenBlocks`, `grade`, `handoutDraftId`, `handoutId`, `handoutSnapshotId`, `handoutVersionId`, `knowledgePointId`, `lectureId`, `moduleId`, `stage`, `subject`, `term`, `title`, `versionDisplayName` |
| `exportRequests` | 6 | `audiences`, `exportRequestId`, `formats`, `handoutSnapshotIds`, `retryOfExportJobId`, `submittedAt` |
| `exportFiles` | 3 | `audience`, `exportFileId`, `fileName`, `format`, `handoutSnapshotId`, `url` |
| `exportJobs` | 8 | `audience`, `cancelledAt`, `completedAt`, `createdAt`, `exportFileId`, `exportJobId`, `exportRequestId`, `failedAt`, `format`, `handoutSnapshotId`, `retryOfExportJobId`, `status`, `subject` |
| `effectiveQuestions` | 85 | `analysis`, `answer`, `approvedAt`, `approvedVersion`, `assets`, `children`, `content`, `contentStructure`, `difficultyStars`, `displayBlocks`, `effectiveSource`, `grade`, `images`, `knowledgeTreePath`, `lesson`, `lineageId`, `material`, `options`, `primaryKnowledgeTag`, `provenance`, `questionId`, `questionType`, `richHtmlByPartKey`, `secondaryKnowledgeTags`, `sourceDatasetId`, `sourceDocumentId`, `sourceEntityId`, `sourceQuestionId`, `sourceTaskId`, `stage`, `stem`, `subject`, `title` |
| `replacementCandidates` | 2 | `courseNodeId`, `knowledgePointId`, `lectureId`, `replacementCandidateId`, `replacementQuestionId`, `returnQuestionId`, `subject` |

## Editor Persistence

- PASS: Tiptap JSON is read from editor.getJSON()
- PASS: master plus per-version overrides are persisted
- PASS: question references pin questionId and revisionId
- PASS: knowledge references pin knowledgeId and revisionId
- PASS: safety snapshots exist
- PASS: export snapshots are immutable copies in the prototype flow
- PASS: preview confirmation is explicit before export

Question reference override fields: `overrideAnalysisHtml`, `overrideAnalysisMarkdown`, `overrideAnswerHtml`, `overrideAnswerMarkdown`, `overrideBlockType`, `overrideContentHtml`, `overrideContentMarkdown`, `overrideDifficultyStars`, `overrideKnowledgeCategory`, `overrideKnowledgeTags`, `overrideKnowledgeTreePath`, `overrideLecturePoint`, `overrideOptionsHtml`, `overrideOptionsText`, `overridePrimaryKnowledgeTag`, `overrideQuestionPosition`, `overrideQuestionType`, `overrideStemHtml`, `overrideStemMarkdown`, `overrideSubject`, `overrideTitle`, `overrideTitleHtml`

## Backend Implications

- Question identity and question revision must be separate because editor references pin both values.
- Human review must bind to a question revision; editing content creates an unreviewed revision.
- The handout model needs a master document, three version projections or overrides, drafts, immutable revisions, confirmations, and export snapshots.
- Question, knowledge, and file references need relational projections even when Tiptap JSON remains the canonical editor payload.
- Published snapshots must freeze question content and assets so later question edits do not mutate an exported handout.
- Source provenance needs structured file, page or block evidence; a display string alone is insufficient.

## Limitations

- The prototype is a high-fidelity local application, not a committed backend API contract.
- Field presence demonstrates UI demand but does not establish database cardinality or authorization rules.
- The inventory does not treat page identifiers such as S01-S07 as backend module boundaries.

