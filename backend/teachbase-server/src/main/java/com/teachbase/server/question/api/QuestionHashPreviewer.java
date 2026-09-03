package com.teachbase.server.question.api;

/**
 * 中文维护说明：本文件属于题目、修订与检索模块的对外稳定合同层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Read-only canonical hashing port used by dry-run ingestion validation.
 */
public interface QuestionHashPreviewer {

    QuestionHashPreview previewHashes(QuestionImportItem item);
}
