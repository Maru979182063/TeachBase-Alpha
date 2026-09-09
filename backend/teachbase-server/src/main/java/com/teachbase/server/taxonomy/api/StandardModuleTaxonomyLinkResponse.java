package com.teachbase.server.taxonomy.api;

import java.util.UUID;

/** 中文维护说明：模块 taxonomy 关系幂等写入后的稳定响应。 */
public record StandardModuleTaxonomyLinkResponse(
        UUID standardModuleTaxonomyLinkId,
        UUID standardModuleRevisionId,
        UUID taxonomyNodeId,
        String relationType) {
}
