package com.teachbase.server.standardmodule.api;

import java.util.List;
import java.util.UUID;

/** 中文维护说明：按 workspace 和精确 revision id 查询模块，禁止跨租户或隐式读取 latest。 */
public interface StandardModuleRevisionDirectory {
    List<StandardModuleRevisionDescriptor> findAll(UUID workspaceId, List<UUID> revisionIds);
}
