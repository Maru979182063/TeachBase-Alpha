package com.teachbase.server.governanceprojection.application;

import static com.teachbase.server.governanceprojection.application.GovernanceProjectionHasher.*;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Optional;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * 中文维护说明：claim、投影和失败登记使用短事务；投影失败绝不能回滚已经提交的教师事实。
 */
@Service
public class GovernanceProjectionCoordinator {

    private final GovernanceProjectionRepository repository;
    private final TransactionTemplate transactions;

    public GovernanceProjectionCoordinator(
            GovernanceProjectionRepository repository, PlatformTransactionManager transactionManager) {
        this.repository = repository;
        this.transactions = new TransactionTemplate(transactionManager);
    }

    public int drain(String workerId, Duration leaseDuration, Duration retryDelay, int maxEvents) {
        int processed = 0;
        for (int index = 0; index < maxEvents; index++) {
            OffsetDateTime now = now();
            Optional<GovernanceProjectionRepository.ClaimedEvent> claimed = transactions.execute(status ->
                    repository.claimNext(workerId, now, now.plus(leaseDuration)));
            if (claimed == null || claimed.isEmpty()) break;
            var event = claimed.get();
            try {
                transactions.executeWithoutResult(status -> project(event));
                processed++;
            } catch (RuntimeException exception) {
                String code = stableError(exception);
                transactions.executeWithoutResult(status -> repository.markFailed(
                        event.eventId(), workerId, now().plus(retryDelay), code));
            }
        }
        return processed;
    }

    private void project(GovernanceProjectionRepository.ClaimedEvent claim) {
        var event = repository.lockClaim(claim.eventId(), claim.workerId(), now())
                .orElseThrow(() -> new IllegalStateException("governance_projection_lease_lost"));
        if (event.domain().equals("TAG")) {
            TagAuthority authority = repository.loadTagAuthority(event.authorityStateId(), false)
                    .orElseThrow(() -> new IllegalStateException("tag_projection_authority_missing"));
            assertNotBehind(event, authority.stateVersion());
            repository.upsertTag(
                    authority,
                    stableProjectionId("TAG", authority.workspaceId(), authority.questionRevisionId(),
                            authority.taxonomyKey()),
                    tagHash(authority), now());
        } else if (event.domain().equals("DIFFICULTY")) {
            DifficultyAuthority authority = repository.loadDifficultyAuthority(event.authorityStateId(), false)
                    .orElseThrow(() -> new IllegalStateException("difficulty_projection_authority_missing"));
            assertNotBehind(event, authority.stateVersion());
            repository.upsertDifficulty(
                    authority,
                    stableProjectionId("DIFFICULTY", authority.workspaceId(), authority.questionRevisionId(),
                            authority.rubricKey() + "|" + authority.contextKey()),
                    difficultyHash(authority), now());
        } else {
            throw new IllegalStateException("governance_projection_domain_unknown");
        }
        repository.markProcessed(event.eventId(), event.workerId(), now());
    }

    private void assertNotBehind(GovernanceProjectionRepository.ClaimedEvent event, long currentVersion) {
        if (currentVersion < event.authorityStateVersion()) {
            throw new IllegalStateException("governance_projection_authority_version_regressed");
        }
    }

    private String stableError(RuntimeException exception) {
        String value = exception.getMessage();
        return value != null && value.matches("[a-z0-9_:-]+") ? value : "governance_projection_failed";
    }

    private OffsetDateTime now() {
        return OffsetDateTime.now(ZoneOffset.UTC);
    }
}
