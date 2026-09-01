package com.teachbase.server.releaseseed.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.source.api.RegisterSourceDocumentCommand;
import com.teachbase.server.source.api.RegisterSourceRegionCommand;
import com.teachbase.server.source.api.SourceCatalog;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Processes one source document or region in an independently recoverable transaction.
 */
@Service
public class ReleaseSeedSourceProcessor {

    private final ReleaseSeedAssetPublisher assets;
    private final SourceCatalog sources;
    private final ReleaseSeedRepository checkpoints;
    private final ObjectMapper objectMapper;

    public ReleaseSeedSourceProcessor(
            ReleaseSeedAssetPublisher assets,
            SourceCatalog sources,
            ReleaseSeedRepository checkpoints,
            ObjectMapper objectMapper) {
        this.assets = assets;
        this.sources = sources;
        this.checkpoints = checkpoints;
        this.objectMapper = objectMapper;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void processDocument(
            ReleaseSeedBatchLease lease,
            ValidatedReleaseSeedPackage seedPackage,
            ReleaseSeedProperties properties,
            JsonNode document) {
        String key = document.path("sourceDocumentKey").asText();
        if (checkpoints.findSourceDocument(lease.releaseSeedBatchId(), key).isPresent()) return;
        String assetPath = document.path("assetPath").asText();
        String mediaType = document.path("mediaType").asText("application/octet-stream");
        String assetSha = document.path("assetSha256").asText();
        var file = assets.publish(
                properties.workspaceId(), properties.actorUserId(), seedPackage.root(), properties.storageRoot(),
                seedPackage.packageContentHash(), assetPath, mediaType, assetSha);
        var metadata = objectMapper.createObjectNode();
        metadata.put("sourceSystem", document.path("sourceSystem").asText());
        metadata.put("originalFileSha256", document.path("originalFileSha256").asText());
        metadata.put("releaseSeedBatchId", seedPackage.batchId());
        var registered = sources.registerDocument(new RegisterSourceDocumentCommand(
                properties.workspaceId(), properties.actorUserId(), file.fileVersionId(),
                document.path("sourceSystem").asText() + ":" + key,
                sourceType(mediaType, assetPath), text(document, "subject", properties.defaultSubject()),
                text(document, "stage", properties.defaultStage()),
                text(document, "grade", properties.defaultGrade()), text(document, "title", key), metadata));
        checkpoints.mapSourceDocument(
                lease.releaseSeedBatchId(), properties.workspaceId(), key,
                registered.id(), file.fileVersionId(), assetSha);
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void processRegion(
            ReleaseSeedBatchLease lease,
            ValidatedReleaseSeedPackage seedPackage,
            ReleaseSeedProperties properties,
            JsonNode region) {
        String regionKey = region.path("sourceRegionKey").asText();
        if (checkpoints.findSourceRegion(lease.releaseSeedBatchId(), regionKey).isPresent()) return;
        String documentKey = region.path("sourceDocumentKey").asText();
        var document = checkpoints.findSourceDocument(lease.releaseSeedBatchId(), documentKey)
                .orElseThrow(() -> new ReleaseSeedValidationException("release_seed_source_document_map_missing"));
        JsonNode locator = region.path("locator");
        var registered = sources.registerRegion(new RegisterSourceRegionCommand(
                properties.workspaceId(), properties.actorUserId(), document.sourceDocumentId(),
                regionKey,
                regionType(locator), integer(locator, "page"), integer(locator, "order"),
                locator.path("bbox").isObject() ? locator.path("bbox") : null,
                region.path("extractedText").asText(""), locator.deepCopy()));
        checkpoints.mapSourceRegion(
                lease.releaseSeedBatchId(), properties.workspaceId(), regionKey, documentKey, registered.id());
    }

    private String sourceType(String mediaType, String assetPath) {
        String lower = assetPath.toLowerCase(java.util.Locale.ROOT);
        if (lower.endsWith(".pdf") || mediaType.equals("application/pdf")) return "pdf";
        if (lower.endsWith(".docx") || mediaType.contains("wordprocessingml")) return "docx";
        if (mediaType.startsWith("image/")) return "image";
        return "structured_import";
    }

    private String regionType(JsonNode locator) {
        String kind = locator.path("kind").asText("").toLowerCase(java.util.Locale.ROOT);
        return switch (kind) {
            case "page" -> "page";
            case "image" -> "image";
            case "formula" -> "formula";
            case "table" -> "table";
            default -> "question";
        };
    }

    private Integer integer(JsonNode node, String field) {
        return node.path(field).isIntegralNumber() ? node.path(field).asInt() : null;
    }

    private String text(JsonNode node, String field, String fallback) {
        return node.path(field).isTextual() && !node.path(field).asText().isBlank()
                ? node.path(field).asText().strip()
                : fallback;
    }
}
