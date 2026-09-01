package com.teachbase.server.collection.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于题篮与快照模块的对外稳定合同层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：One current basket item in stable display order.
 */
public record CollectionItemResponse(
        UUID questionId,
        UUID questionRevisionId,
        int positionIndex,
        JsonNode settings) {
}
