package com.teachbase.server.fileasset.api;

import java.util.UUID;

/** 中文维护说明：入库编排在成员校验后核实同工作空间文件版本与声明哈希，不暴露持久层对象。 */
public interface FileVersionEvidence {
    boolean matches(UUID workspaceId, UUID fileVersionId, String sha256);
}
