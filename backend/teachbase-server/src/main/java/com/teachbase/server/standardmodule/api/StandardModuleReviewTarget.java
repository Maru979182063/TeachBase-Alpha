package com.teachbase.server.standardmodule.api;

import java.util.UUID;

/** 中文维护说明：Review 打开 case 时冻结的模块修订身份和内容哈希。 */
public record StandardModuleReviewTarget(
        UUID standardModuleId,
        UUID standardModuleRevisionId,
        String reviewStatus,
        String contentHash) {
}
