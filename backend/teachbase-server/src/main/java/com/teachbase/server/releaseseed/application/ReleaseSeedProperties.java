package com.teachbase.server.releaseseed.application;

import java.nio.file.Path;
import java.time.Duration;
import java.util.UUID;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 中文维护说明：本文件属于首发数据包导入模块的业务规则与事务编排层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Environment-bound command settings; paths are runtime inputs and never persisted as contracts.
 */
@ConfigurationProperties("teachbase.release-seed")
public record ReleaseSeedProperties(
        String mode,
        Path packageRoot,
        Path reportPath,
        Path storageRoot,
        UUID workspaceId,
        UUID actorUserId,
        UUID taxonomyVersionId,
        String defaultSubject,
        String defaultStage,
        String defaultGrade,
        String defaultQuestionType,
        Integer failAfterItems,
        Duration leaseDuration) {

    public Duration effectiveLeaseDuration() {
        return leaseDuration == null ? Duration.ofSeconds(30) : leaseDuration;
    }

    public int effectiveFailAfterItems() {
        return failAfterItems == null ? 0 : failAfterItems;
    }
}
