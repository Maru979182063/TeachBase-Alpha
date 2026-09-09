package com.teachbase.server.fileasset.api;

import java.util.List;
import java.util.UUID;

/** 中文维护说明：按 workspace 批量核验 Canonical Import 引用的既有 file version。 */
public interface FileVersionDirectory {

    List<FileVersionDescriptor> findAll(UUID workspaceId, List<UUID> fileVersionIds);
}
