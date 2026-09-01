package com.teachbase.server.question.api;

import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，封装跨层调用参数，不能用它绕过对应应用服务的校验。
 *
 * 英文术语对照：Stable graph edge between two question identities.
 */
public record QuestionRelationCommand(
        UUID workspaceId,
        UUID parentQuestionId,
        UUID childQuestionId,
        String relationType,
        int sortOrder) {
}
