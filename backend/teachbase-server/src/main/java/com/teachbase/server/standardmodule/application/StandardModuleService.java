package com.teachbase.server.standardmodule.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import com.teachbase.server.standardmodule.api.CreateStandardModuleRequest;
import com.teachbase.server.standardmodule.api.CreateStandardModuleRevisionRequest;
import com.teachbase.server.standardmodule.api.LinkStandardModuleFileRequest;
import com.teachbase.server.standardmodule.api.LinkStandardModuleSourceRequest;
import com.teachbase.server.standardmodule.api.StandardModuleLinkResponse;
import com.teachbase.server.standardmodule.api.StandardModuleResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Iterator;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 中文维护说明：标准模块应用服务负责租户校验、规范 JSON 哈希和追加式修订；
 * module type 属于稳定身份，不能在修订时偷偷改变。
 */
@Service
public class StandardModuleService {

    private final WorkspaceDirectory workspaces;
    private final StandardModuleRepository modules;
    private final AuditTrail auditTrail;
    private final ObjectMapper objectMapper;

    public StandardModuleService(
            WorkspaceDirectory workspaces,
            StandardModuleRepository modules,
            AuditTrail auditTrail,
            ObjectMapper objectMapper) {
        this.workspaces = workspaces;
        this.modules = modules;
        this.auditTrail = auditTrail;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public StandardModuleResponse create(CreateStandardModuleRequest request) {
        validateActor(request.workspaceId(), request.actorUserId());
        var input = input(
                request.workspaceId(), request.actorUserId(), request.moduleKey(), request.moduleType(),
                request.title(), request.subject(), request.stage(), request.grade(),
                request.schemaVersion(), request.content());
        var result = modules.create(input);
        if (result.createdRevision()) audit(request.workspaceId(), request.actorUserId(), result, "standard_module.created");
        return result;
    }

    @Transactional
    public StandardModuleResponse revise(UUID standardModuleId, CreateStandardModuleRevisionRequest request) {
        validateActor(request.workspaceId(), request.actorUserId());
        var input = input(
                request.workspaceId(), request.actorUserId(), "", "", request.title(), request.subject(),
                request.stage(), request.grade(), request.schemaVersion(), request.content());
        var result = modules.revise(standardModuleId, input);
        if (result.createdRevision()) audit(request.workspaceId(), request.actorUserId(), result, "standard_module.revised");
        return result;
    }

    @Transactional
    public StandardModuleLinkResponse linkSource(
            UUID standardModuleRevisionId, LinkStandardModuleSourceRequest request) {
        validateActor(request.workspaceId(), request.actorUserId());
        if (!request.sourceReference().isObject()) {
            throw new StandardModuleValidationException("standard_module_source_reference_invalid");
        }
        if (request.sourceRegionId() != null && request.sourceDocumentId() == null) {
            throw new StandardModuleValidationException("standard_module_source_document_required");
        }
        var result = modules.linkSource(
                request.workspaceId(), standardModuleRevisionId, clean(request.sourceEvidenceKey()),
                request.sourceDocumentId(), request.sourceRegionId(), clean(request.sourceRole()),
                request.sourceReference());
        auditTrail.record(new AuditCommand(
                request.workspaceId(), request.actorUserId(), "standard_module.source_linked",
                "standard_module_revision", standardModuleRevisionId,
                Map.of("sourceEvidenceKey", clean(request.sourceEvidenceKey()), "created", result.created())));
        return result;
    }

    @Transactional
    public StandardModuleLinkResponse linkFile(
            UUID standardModuleRevisionId, LinkStandardModuleFileRequest request) {
        validateActor(request.workspaceId(), request.actorUserId());
        if (!request.metadata().isObject()) {
            throw new StandardModuleValidationException("standard_module_file_metadata_invalid");
        }
        var result = modules.linkFile(
                request.workspaceId(), standardModuleRevisionId, request.fileVersionId(),
                clean(request.referenceKey()), clean(request.referenceRole()), request.metadata());
        auditTrail.record(new AuditCommand(
                request.workspaceId(), request.actorUserId(), "standard_module.file_linked",
                "standard_module_revision", standardModuleRevisionId,
                Map.of("referenceKey", clean(request.referenceKey()), "created", result.created())));
        return result;
    }

    @Transactional(readOnly = true)
    public long usageCount(UUID workspaceId, UUID actorUserId, UUID standardModuleRevisionId) {
        validateActor(workspaceId, actorUserId);
        return modules.usageCount(workspaceId, standardModuleRevisionId);
    }

    private StandardModuleRevisionInput input(
            UUID workspaceId, UUID actorUserId, String moduleKey, String moduleType, String title,
            String subject, String stage, String grade, int schemaVersion, JsonNode content) {
        if (schemaVersion <= 0) throw new StandardModuleValidationException("standard_module_schema_invalid");
        if (content == null || !content.isObject()) {
            throw new StandardModuleValidationException("standard_module_content_invalid");
        }
        JsonNode canonical = canonicalize(content);
        return new StandardModuleRevisionInput(
                workspaceId, actorUserId, clean(moduleKey), clean(moduleType), clean(title), clean(subject),
                clean(stage), clean(grade), schemaVersion, canonical,
                hash(clean(title), clean(subject), clean(stage), clean(grade), schemaVersion, canonical));
    }

    private JsonNode canonicalize(JsonNode node) {
        if (node.isObject()) {
            ObjectNode result = objectMapper.createObjectNode();
            Map<String, JsonNode> fields = new TreeMap<>();
            Iterator<Map.Entry<String, JsonNode>> iterator = node.fields();
            iterator.forEachRemaining(entry -> fields.put(entry.getKey(), entry.getValue()));
            fields.forEach((key, value) -> result.set(key, canonicalize(value)));
            return result;
        }
        if (node.isArray()) {
            ArrayNode result = objectMapper.createArrayNode();
            node.forEach(item -> result.add(canonicalize(item)));
            return result;
        }
        return node.deepCopy();
    }

    private String hash(
            String title, String subject, String stage, String grade, int schemaVersion, JsonNode content) {
        ObjectNode envelope = objectMapper.createObjectNode();
        envelope.put("title", title);
        envelope.put("subject", subject);
        envelope.put("stage", stage);
        envelope.put("grade", grade);
        envelope.put("schemaVersion", schemaVersion);
        envelope.set("content", content);
        try {
            return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(objectMapper.writeValueAsString(envelope).getBytes(StandardCharsets.UTF_8)));
        } catch (JsonProcessingException exception) {
            throw new StandardModuleValidationException("standard_module_content_not_serializable");
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

    private void audit(UUID workspaceId, UUID actorUserId, StandardModuleResponse result, String event) {
        auditTrail.record(new AuditCommand(
                workspaceId, actorUserId, event, "standard_module", result.standardModuleId(),
                Map.of("standardModuleRevisionId", result.standardModuleRevisionId().toString(),
                        "contentHash", result.contentHash())));
    }

    private String clean(String value) {
        return value == null ? "" : value.trim();
    }
}
