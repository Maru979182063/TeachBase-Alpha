package com.teachbase.server.editor.api;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于在线编辑文档模块的对外稳定合同层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Display contract for one concrete question revision inserted into an editor draft.
 */
public record QuestionPlacementItem(
        @NotNull UUID questionRevisionId,
        @NotBlank String displayMode,
        boolean showAnswer,
        boolean showAnalysis) {
}
