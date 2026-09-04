package com.teachbase.server.fileasset.api;

import java.util.Optional;
import java.util.UUID;

/** 中文维护说明：渲染器只能查找同工作空间已登记的不可变文件，不能信任引用正文提供的磁盘路径。 */
public interface StoredFileDirectory {
    Optional<StoredFile> findBySha256(UUID workspaceId, String sha256);

    /** 中文维护说明：相对存储键与字节哈希共同约束文件读取，导出仍须核对实际文件。 */
    record StoredFile(String storageKey, String sha256, String mediaType, long sizeBytes) {
    }
}
