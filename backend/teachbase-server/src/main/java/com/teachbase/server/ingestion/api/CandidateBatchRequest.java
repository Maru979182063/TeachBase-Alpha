package com.teachbase.server.ingestion.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.question.api.QuestionImportItem;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.UUID;

/** 中文维护说明：文件须先通过存储适配器保存并登记；来源哈希构成不可变文档身份。 */
public record CandidateBatchRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotNull UUID sourceFileVersionId,
        @NotBlank @Pattern(regexp = "[0-9a-f]{64}") String sourceSha256,
        @NotBlank @Pattern(regexp = "docx|pdf") String sourceType,
        @NotBlank @Size(max = 80) String subject,
        @Size(max = 512) String title,
        @NotNull JsonNode sourceMetadata,
        @NotEmpty @Size(max = 100) List<@Valid QuestionImportItem> questions) {
}
