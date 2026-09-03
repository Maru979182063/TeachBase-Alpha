package com.teachbase.server.fileasset.api;

import com.teachbase.server.fileasset.application.FileRegistration;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于文件资产模块的对外稳定合同层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Registered logical file and immutable version identity returned to clients.
 */
public record FileRegistrationResponse(
        UUID fileAssetId,
        UUID fileVersionId,
        UUID workspaceId,
        String originalFilename,
        String storageProvider,
        String storageKey,
        String mediaType,
        long sizeBytes,
        String sha256,
        boolean created) {

    static FileRegistrationResponse from(FileRegistration registration) {
        return new FileRegistrationResponse(
                registration.fileAssetId(),
                registration.fileVersionId(),
                registration.workspaceId(),
                registration.originalFilename(),
                registration.storageProvider(),
                registration.storageKey(),
                registration.mediaType(),
                registration.sizeBytes(),
                registration.sha256(),
                registration.created());
    }
}
