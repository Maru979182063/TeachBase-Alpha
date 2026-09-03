package com.teachbase.server.editor.api;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于在线编辑文档模块的对外稳定合同层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Batch placement is one idempotent working-draft mutation.
 */
public record PlaceQuestionReferencesRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @Positive Long expectedDraftVersion,
        @Positive Long expectedRevisionNo,
        @Size(max = 128) String clientMutationId,
        int insertionIndex,
        @NotEmpty List<String> targetLayers,
        @NotEmpty @Size(max = 200) List<@Valid QuestionPlacementItem> questions) {
}
