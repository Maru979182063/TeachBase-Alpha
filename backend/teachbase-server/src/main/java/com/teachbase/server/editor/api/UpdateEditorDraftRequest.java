package com.teachbase.server.editor.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于在线编辑文档模块的对外稳定合同层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Idempotent full-document autosave based on the expected working-draft version.
 */
public record UpdateEditorDraftRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @Positive Long expectedDraftVersion,
        @Positive Long expectedRevisionNo,
        @Size(max = 128) String clientMutationId,
        int schemaVersion,
        @NotNull JsonNode masterDoc,
        @NotNull JsonNode versionOverrides) {
}
