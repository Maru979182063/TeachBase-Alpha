package com.teachbase.server.releaseseed.application;

import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 中文维护说明：本文件属于首发数据包导入模块的业务规则与事务编排层，负责业务校验和用例编排，不应泄漏数据库记录或传输层对象。
 *
 * 英文术语对照：Defines short transaction boundaries around lease acquisition and completion.
 */
@Service
public class ReleaseSeedCheckpointService {

    private final ReleaseSeedRepository repository;
    private final AuditTrail auditTrail;

    public ReleaseSeedCheckpointService(ReleaseSeedRepository repository, AuditTrail auditTrail) {
        this.repository = repository;
        this.auditTrail = auditTrail;
    }

    @Transactional
    public ReleaseSeedBatchLease acquire(
            ValidatedReleaseSeedPackage seedPackage,
            ReleaseSeedProperties properties) {
        return repository.acquire(
                properties.workspaceId(), properties.actorUserId(), properties.taxonomyVersionId(),
                seedPackage, properties.effectiveLeaseDuration());
    }

    @Transactional
    public ReleaseSeedBatchLease complete(
            ReleaseSeedBatchLease lease,
            ValidatedReleaseSeedPackage seedPackage,
            ReleaseSeedProperties properties) {
        var completed = repository.complete(lease.releaseSeedBatchId(), lease.workerToken());
        auditTrail.record(new AuditCommand(
                properties.workspaceId(), properties.actorUserId(), "release_seed.completed", "release_seed_batch",
                lease.releaseSeedBatchId(), Map.of(
                        "batchId", seedPackage.batchId(),
                        "releaseVersion", seedPackage.releaseVersion(),
                        "packageContentHash", seedPackage.packageContentHash(),
                        "questionCount", seedPackage.questions().size())));
        return completed;
    }

    @Transactional
    public void fail(ReleaseSeedBatchLease lease, String code) {
        repository.fail(lease.releaseSeedBatchId(), lease.workerToken(), code);
    }

    @Transactional(readOnly = true)
    public ReleaseSeedBatchLease find(ValidatedReleaseSeedPackage seedPackage, ReleaseSeedProperties properties) {
        return repository.find(properties.workspaceId(), seedPackage.packageContentHash());
    }

    @Transactional(readOnly = true)
    public ReleaseSeedVerification verify(ReleaseSeedBatchLease lease) {
        return repository.verify(lease.releaseSeedBatchId());
    }
}
