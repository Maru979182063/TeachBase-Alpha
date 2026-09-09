package com.teachbase.server.standardmodule.api;

import java.util.UUID;

/** 中文维护说明：来源或文件关系写入后的幂等结果。 */
public record StandardModuleLinkResponse(UUID linkId, boolean created) {
}
