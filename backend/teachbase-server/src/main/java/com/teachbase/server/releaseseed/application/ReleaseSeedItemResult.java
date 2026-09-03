package com.teachbase.server.releaseseed.application;

import java.util.UUID;

/**
 * 中文维护说明：本文件属于首发数据包导入模块的业务规则与事务编排层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Imported question identity and review case persisted at one checkpoint.
 */
public record ReleaseSeedItemResult(
        UUID questionId,
        UUID questionRevisionId,
        UUID reviewCaseId,
        boolean createdQuestion,
        boolean createdRevision) {
}
