package com.teachbase.server.canonicalimport.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.teachbase.server.canonicalimport.api.CanonicalImportActionRequest;
import com.teachbase.server.canonicalimport.api.CanonicalImportOperationResponse;
import com.teachbase.server.canonicalimport.api.CanonicalImportStatusResponse;
import com.teachbase.server.canonicalimport.api.ValidateCanonicalImportRequest;
import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * 中文维护说明：Validate 只冻结 package 与 DAG；Commit/Resume 以短事务逐 operation 推进。
 * 已完成 operation 永不重跑，失败或进程中断后由租约接管未完成 frontier。
 */
@Service
public class CanonicalImportService {

    private final CanonicalImportPlanner planner;
    private final CanonicalImportRepository repository;
    private final CanonicalImportOperationExecutor executor;
    private final CanonicalImportProperties properties;
    private final WorkspaceDirectory workspaces;
    private final ObjectMapper mapper;
    private final TransactionTemplate transactions;

    public CanonicalImportService(
            CanonicalImportPlanner planner,
            CanonicalImportRepository repository,
            CanonicalImportOperationExecutor executor,
            CanonicalImportProperties properties,
            WorkspaceDirectory workspaces,
            ObjectMapper mapper,
            PlatformTransactionManager transactionManager) {
        this.planner = planner;
        this.repository = repository;
        this.executor = executor;
        this.properties = properties;
        this.workspaces = workspaces;
        this.mapper = mapper;
        this.transactions = new TransactionTemplate(transactionManager);
    }

    public CanonicalImportStatusResponse validate(ValidateCanonicalImportRequest request) {
        validateActor(request.workspaceId(), request.actorUserId());
        CanonicalImportPlan plan = planner.plan(
                request.workspaceId(), request.actorUserId(), request.contentPackage(), request.packageHash());
        var saved = transactions.execute(status -> repository.saveValidation(
                request.workspaceId(), request.actorUserId(), plan));
        return response(saved.request(), saved.replayed());
    }

    public CanonicalImportStatusResponse commit(UUID requestId, CanonicalImportActionRequest action) {
        return run(requestId, action);
    }

    public CanonicalImportStatusResponse resume(UUID requestId, CanonicalImportActionRequest action) {
        return run(requestId, action);
    }

    public CanonicalImportStatusResponse status(UUID requestId, UUID workspaceId, UUID actorUserId) {
        validateActor(workspaceId, actorUserId);
        return response(repository.requireRequest(requestId, workspaceId), false);
    }

    public CanonicalImportStatusResponse verify(UUID requestId, CanonicalImportActionRequest action) {
        validateAction(requestId, action);
        ImportRequestRecord request = repository.requireRequest(requestId, action.workspaceId());
        List<ImportOperationRecord> operations = repository.operations(requestId, action.workspaceId());
        if (!"completed".equals(request.status()) || operations.stream().anyMatch(op -> !"completed".equals(op.status()))) {
            throw new CanonicalImportConflictException("canonical_import_not_complete");
        }
        String fingerprint = fingerprint(request, operations);
        if (!fingerprint.equals(request.resultFingerprint())) {
            throw new CanonicalImportConflictException("canonical_import_result_fingerprint_mismatch");
        }
        repository.assertCompletedTargetsExist(requestId, action.workspaceId());
        return response(request, true);
    }

    private CanonicalImportStatusResponse run(UUID requestId, CanonicalImportActionRequest action) {
        validateAction(requestId, action);
        UUID token = UUID.randomUUID();
        repository.assertCompletedTargetsExist(requestId, action.workspaceId());
        ImportRequestRecord acquired = transactions.execute(status -> repository.acquire(
                requestId, action.workspaceId(), token, properties.leaseDuration()));
        if ("completed".equals(acquired.status())) return response(acquired, true);

        while (true) {
            List<ImportOperationRecord> snapshot = repository.operations(requestId, action.workspaceId());
            Map<String, ImportOperationRecord> completed = new LinkedHashMap<>();
            snapshot.stream().filter(op -> "completed".equals(op.status()))
                    .forEach(op -> completed.put(op.operationKey(), op));
            ImportOperationRecord next = snapshot.stream()
                    .filter(op -> !"completed".equals(op.status()))
                    .findFirst().orElse(null);
            if (next == null) {
                ImportRequestRecord current = repository.requireRequest(requestId, action.workspaceId());
                String fingerprint = fingerprint(current, snapshot);
                transactions.executeWithoutResult(status -> repository.completeRequest(requestId, token, fingerprint));
                return response(repository.requireRequest(requestId, action.workspaceId()), false);
            }
            assertDependencies(next, completed);
            try {
                transactions.executeWithoutResult(status -> {
                    repository.markRunning(
                            requestId, token, next.importOperationId(), properties.leaseDuration());
                    inject(action.testFaultBeforeOperationKey(), next.operationKey(), "before");
                    ImportOperationOutcome outcome = executor.execute(
                            action.workspaceId(), action.actorUserId(), next, completed);
                    inject(action.testFaultAfterOperationKey(), next.operationKey(), "after");
                    repository.complete(next.importOperationId(), outcome);
                });
            } catch (RuntimeException exception) {
                String code = exception instanceof CanonicalImportInjectedFailureException
                        ? exception.getMessage() : "canonical_import_operation_failed";
                String detail = exception.getMessage() == null ? exception.getClass().getSimpleName() : exception.getMessage();
                transactions.executeWithoutResult(status -> repository.fail(
                        requestId, next.importOperationId(), code, detail));
                throw exception;
            }
        }
    }

    private void validateAction(UUID requestId, CanonicalImportActionRequest action) {
        validateActor(action.workspaceId(), action.actorUserId());
        ImportRequestRecord request = repository.requireRequest(requestId, action.workspaceId());
        if (!request.actorUserId().equals(action.actorUserId())) {
            throw new ActorNotWorkspaceMemberException();
        }
        if (!request.packageHash().equals(action.packageHash().trim().toLowerCase(java.util.Locale.ROOT))) {
            throw new CanonicalImportConflictException("canonical_import_action_package_hash_mismatch");
        }
        if (!properties.faultInjectionEnabled()
                && (present(action.testFaultBeforeOperationKey()) || present(action.testFaultAfterOperationKey()))) {
            throw new CanonicalImportConflictException("canonical_import_fault_injection_disabled");
        }
    }

    private void assertDependencies(ImportOperationRecord operation, Map<String, ImportOperationRecord> completed) {
        for (var dependency : operation.dependencies()) {
            if (!completed.containsKey(dependency.asText())) {
                throw new CanonicalImportConflictException(
                        "canonical_import_dependency_not_completed:" + dependency.asText());
            }
        }
    }

    private void inject(String requested, String operationKey, String phase) {
        if (present(requested) && requested.trim().equals(operationKey)) {
            throw new CanonicalImportInjectedFailureException(
                    "canonical_import_injected_failure:" + phase + ":" + operationKey);
        }
    }

    private CanonicalImportStatusResponse response(ImportRequestRecord request, boolean replayed) {
        List<CanonicalImportOperationResponse> operations = repository.operations(
                request.importRequestId(), request.workspaceId()).stream().map(op -> new CanonicalImportOperationResponse(
                        op.operationKey(), op.operationType(), op.sequenceNo(), op.dependencies(), op.status(),
                        op.attemptNo(), op.targetId(), op.targetRevisionId(), op.targetHash(), op.result(), op.error(),
                        op.startedAt(), op.completedAt())).toList();
        return new CanonicalImportStatusResponse(
                request.importRequestId(), request.workspaceId(), request.producer(), request.contractVersion(),
                request.packageKey(), request.packageHash(), request.status(), request.operationCount(),
                request.completedOperationCount(), request.attemptNo(), request.resultFingerprint(),
                request.failureSummary(), request.createdAt(), request.startedAt(), request.completedAt(),
                replayed, operations);
    }

    private String fingerprint(ImportRequestRecord request, List<ImportOperationRecord> operations) {
        ObjectNode root = mapper.createObjectNode();
        root.put("packageHash", request.packageHash());
        var values = root.putArray("operations");
        operations.stream().sorted(java.util.Comparator.comparingInt(ImportOperationRecord::sequenceNo)).forEach(op -> {
            ObjectNode value = values.addObject();
            value.put("operationKey", op.operationKey());
            value.put("payloadHash", op.payloadHash());
            value.put("targetId", op.targetId() == null ? "" : op.targetId().toString());
            value.put("targetRevisionId", op.targetRevisionId() == null ? "" : op.targetRevisionId().toString());
            value.put("targetHash", op.targetHash() == null ? "" : op.targetHash());
        });
        try {
            return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(mapper.writeValueAsBytes(root)));
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("canonical_import_fingerprint_json_invalid", exception);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("sha256_unavailable", exception);
        }
    }

    private void validateActor(UUID workspaceId, UUID actorUserId) {
        if (workspaceId == null || !workspaces.exists(workspaceId)) throw new WorkspaceNotFoundException();
        if (actorUserId == null || !workspaces.isActiveMember(workspaceId, actorUserId)) {
            throw new ActorNotWorkspaceMemberException();
        }
    }

    private boolean present(String value) {
        return value != null && !value.isBlank();
    }
}
