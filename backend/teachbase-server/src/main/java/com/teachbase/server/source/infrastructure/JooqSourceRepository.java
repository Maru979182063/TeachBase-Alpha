package com.teachbase.server.source.infrastructure;

import static com.teachbase.jooq.tables.SourceDocument.SOURCE_DOCUMENT;
import static com.teachbase.jooq.tables.SourceRegion.SOURCE_REGION;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.source.api.RegisterSourceDocumentCommand;
import com.teachbase.server.source.api.RegisterSourceRegionCommand;
import com.teachbase.server.source.api.SourceRegistration;
import com.teachbase.server.source.application.SourceRepository;
import com.teachbase.server.source.application.SourceValidationException;
import java.time.OffsetDateTime;
import java.util.UUID;
import org.jooq.DSLContext;
import org.jooq.JSON;
import org.springframework.stereotype.Repository;

/**
 * 中文维护说明：本文件属于题源证据模块的数据库或外部工具适配层，负责落实持久化合同；并发正确性最终由事务、锁和数据库约束共同保证。
 *
 * 英文术语对照：jOOQ implementation of external-key source evidence idempotency.
 */
@Repository
class JooqSourceRepository implements SourceRepository {

    private final DSLContext database;
    private final ObjectMapper objectMapper;

    JooqSourceRepository(DSLContext database, ObjectMapper objectMapper) {
        this.database = database;
        this.objectMapper = objectMapper;
    }

    @Override
    public SourceRegistration registerDocument(RegisterSourceDocumentCommand command) {
        UUID candidate = UUID.randomUUID();
        int inserted = database.insertInto(SOURCE_DOCUMENT)
                .set(SOURCE_DOCUMENT.SOURCE_DOCUMENT_ID, candidate)
                .set(SOURCE_DOCUMENT.WORKSPACE_ID, command.workspaceId())
                .set(SOURCE_DOCUMENT.FILE_VERSION_ID, command.fileVersionId())
                .set(SOURCE_DOCUMENT.EXTERNAL_SOURCE_KEY, command.externalSourceKey().strip())
                .set(SOURCE_DOCUMENT.SOURCE_TYPE, command.sourceType())
                .set(SOURCE_DOCUMENT.SUBJECT, clean(command.subject()))
                .set(SOURCE_DOCUMENT.STAGE, clean(command.stage()))
                .set(SOURCE_DOCUMENT.GRADE, clean(command.grade()))
                .set(SOURCE_DOCUMENT.TITLE, clean(command.title()))
                .set(SOURCE_DOCUMENT.STATUS, "ready")
                .set(SOURCE_DOCUMENT.METADATA_JSON, json(command.metadata()))
                .set(SOURCE_DOCUMENT.UPDATED_AT, OffsetDateTime.now())
                .onConflictDoNothing()
                .execute();
        var stored = database.selectFrom(SOURCE_DOCUMENT)
                .where(SOURCE_DOCUMENT.WORKSPACE_ID.eq(command.workspaceId()))
                .and(SOURCE_DOCUMENT.EXTERNAL_SOURCE_KEY.eq(command.externalSourceKey().strip()))
                .fetchOne();
        if (stored == null) {
            stored = database.selectFrom(SOURCE_DOCUMENT)
                    .where(SOURCE_DOCUMENT.WORKSPACE_ID.eq(command.workspaceId()))
                    .and(SOURCE_DOCUMENT.FILE_VERSION_ID.eq(command.fileVersionId()))
                    .fetchOne();
        }
        if (stored == null) throw new IllegalStateException("source_document_registration_failed");
        if (!stored.getFileVersionId().equals(command.fileVersionId())) {
            throw new SourceValidationException("source_document_key_conflict");
        }
        return new SourceRegistration(stored.getSourceDocumentId(), inserted == 1);
    }

    @Override
    public SourceRegistration registerRegion(RegisterSourceRegionCommand command) {
        UUID candidate = UUID.randomUUID();
        int inserted = database.insertInto(SOURCE_REGION)
                .set(SOURCE_REGION.SOURCE_REGION_ID, candidate)
                .set(SOURCE_REGION.SOURCE_DOCUMENT_ID, command.sourceDocumentId())
                .set(SOURCE_REGION.EXTERNAL_REGION_KEY, command.externalRegionKey().strip())
                .set(SOURCE_REGION.REGION_TYPE, command.regionType())
                .set(SOURCE_REGION.PAGE_NO, command.pageNo())
                .set(SOURCE_REGION.ORDER_INDEX, command.orderIndex())
                .set(SOURCE_REGION.BBOX_JSON, command.boundingBox() == null ? null : json(command.boundingBox()))
                .set(SOURCE_REGION.EXTRACTED_TEXT, clean(command.extractedText()))
                .set(SOURCE_REGION.SOURCE_REF_JSON, json(command.sourceReference()))
                .onConflict(SOURCE_REGION.SOURCE_DOCUMENT_ID, SOURCE_REGION.EXTERNAL_REGION_KEY)
                .doNothing()
                .execute();
        var stored = database.selectFrom(SOURCE_REGION)
                .where(SOURCE_REGION.SOURCE_DOCUMENT_ID.eq(command.sourceDocumentId()))
                .and(SOURCE_REGION.EXTERNAL_REGION_KEY.eq(command.externalRegionKey().strip()))
                .fetchOne();
        if (stored == null) throw new IllegalStateException("source_region_registration_failed");
        return new SourceRegistration(stored.getSourceRegionId(), inserted == 1);
    }

    private JSON json(JsonNode value) {
        try {
            return JSON.valueOf(objectMapper.writeValueAsString(value));
        } catch (JsonProcessingException exception) {
            throw new SourceValidationException("source_json_not_serializable");
        }
    }

    private String clean(String value) {
        return value == null ? "" : value.strip();
    }
}
