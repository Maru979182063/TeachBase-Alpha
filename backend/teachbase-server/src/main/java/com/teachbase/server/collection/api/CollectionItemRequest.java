package com.teachbase.server.collection.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotNull;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于题篮与快照模块的对外稳定合同层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Ordered reference to one immutable question revision plus display settings.
 */
public record CollectionItemRequest(@NotNull UUID questionRevisionId, @NotNull JsonNode settings) {
}
