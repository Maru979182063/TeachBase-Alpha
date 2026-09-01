package com.teachbase.server.editor.infrastructure;

import static com.teachbase.jooq.tables.EditorSnapshot.EDITOR_SNAPSHOT;

import com.teachbase.server.editor.api.EditorSnapshotDescriptor;
import com.teachbase.server.editor.api.EditorSnapshotDirectory;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Optional;
import java.util.UUID;
import org.jooq.DSLContext;
import org.springframework.stereotype.Repository;

@Repository
/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，负责落实持久化合同；并发正确性最终由事务、锁和数据库约束共同保证。
 *
 * 英文术语对照：Workspace-scoped jOOQ read adapter for frozen editor snapshots.
 */
class JooqEditorSnapshotDirectory implements EditorSnapshotDirectory {

    private final DSLContext database;
    private final ObjectMapper objectMapper;

    JooqEditorSnapshotDirectory(DSLContext database, ObjectMapper objectMapper) {
        this.database = database;
        this.objectMapper = objectMapper;
    }

    @Override
    public Optional<EditorSnapshotDescriptor> find(UUID editorSnapshotId, UUID workspaceId) {
        return database.select(
                        EDITOR_SNAPSHOT.EDITOR_SNAPSHOT_ID,
                        EDITOR_SNAPSHOT.WORKSPACE_ID,
                        EDITOR_SNAPSHOT.AUDIENCE,
                        EDITOR_SNAPSHOT.SCHEMA_VERSION,
                        EDITOR_SNAPSHOT.FROZEN_CONTENT_JSON,
                        EDITOR_SNAPSHOT.CONTENT_HASH)
                .from(EDITOR_SNAPSHOT)
                .where(EDITOR_SNAPSHOT.EDITOR_SNAPSHOT_ID.eq(editorSnapshotId))
                .and(EDITOR_SNAPSHOT.WORKSPACE_ID.eq(workspaceId))
                .fetchOptional(record -> new EditorSnapshotDescriptor(
                        record.get(EDITOR_SNAPSHOT.EDITOR_SNAPSHOT_ID),
                        record.get(EDITOR_SNAPSHOT.WORKSPACE_ID),
                        record.get(EDITOR_SNAPSHOT.AUDIENCE),
                        record.get(EDITOR_SNAPSHOT.SCHEMA_VERSION),
                        parse(record.get(EDITOR_SNAPSHOT.FROZEN_CONTENT_JSON).data()),
                        record.get(EDITOR_SNAPSHOT.CONTENT_HASH)));
    }

    private com.fasterxml.jackson.databind.JsonNode parse(String json) {
        try {
            return objectMapper.readTree(json);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("stored_editor_snapshot_json_invalid", exception);
        }
    }
}
