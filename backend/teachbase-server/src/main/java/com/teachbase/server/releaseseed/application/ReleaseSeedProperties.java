package com.teachbase.server.releaseseed.application;

import java.nio.file.Path;
import java.time.Duration;
import java.util.UUID;
import org.springframework.boot.context.properties.ConfigurationProperties;

/** Environment-bound command settings; paths are runtime inputs and never persisted as contracts. */
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
