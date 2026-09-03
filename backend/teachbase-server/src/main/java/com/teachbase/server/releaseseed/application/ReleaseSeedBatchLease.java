package com.teachbase.server.releaseseed.application;

import java.util.UUID;

/**
 * 中文维护说明：本文件属于首发数据包导入模块的业务规则与事务编排层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Exclusive import lease and durable resume cursor for one package digest.
 */
public record ReleaseSeedBatchLease(
        UUID releaseSeedBatchId,
        UUID workerToken,
        String status,
        int nextQuestionIndex,
        int attemptNo,
        int questionCount,
        int importedCount,
        int reusedCount,
        int approvedCount) {

    public boolean completed() {
        return status.equals("completed");
    }
}
