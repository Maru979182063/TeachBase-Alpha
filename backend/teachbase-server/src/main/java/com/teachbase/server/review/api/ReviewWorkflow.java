package com.teachbase.server.review.api;

import java.util.UUID;

/**
 * 中文维护说明：本文件属于人工审核模块的对外稳定合同层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Named module port for opening and deciding review cases without persistence coupling.
 */
public interface ReviewWorkflow {

    ReviewCaseResponse open(OpenReviewCaseRequest request);

    ReviewCaseResponse decide(UUID reviewCaseId, DecideReviewCaseRequest request);
}
