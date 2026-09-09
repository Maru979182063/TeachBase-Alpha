package com.teachbase.server.editor.infrastructure;

import static com.teachbase.jooq.tables.EditorRevision.EDITOR_REVISION;

import com.teachbase.server.editor.api.EditorRevisionDescriptor;
import com.teachbase.server.editor.api.EditorRevisionDirectory;
import java.util.Optional;
import java.util.UUID;
import org.jooq.DSLContext;
import org.springframework.stereotype.Repository;

/** 中文维护说明：editor revision 的 workspace-scoped 精确查询适配器。 */
@Repository
class JooqEditorRevisionDirectory implements EditorRevisionDirectory {

    private final DSLContext database;

    JooqEditorRevisionDirectory(DSLContext database) {
        this.database = database;
    }

    @Override
    public Optional<EditorRevisionDescriptor> find(
            UUID workspaceId, UUID editorDocumentId, UUID editorRevisionId) {
        return database.select(
                        EDITOR_REVISION.EDITOR_DOCUMENT_ID,
                        EDITOR_REVISION.EDITOR_REVISION_ID,
                        EDITOR_REVISION.WORKSPACE_ID,
                        EDITOR_REVISION.REVISION_NO,
                        EDITOR_REVISION.CONTENT_HASH)
                .from(EDITOR_REVISION)
                .where(EDITOR_REVISION.WORKSPACE_ID.eq(workspaceId))
                .and(EDITOR_REVISION.EDITOR_DOCUMENT_ID.eq(editorDocumentId))
                .and(EDITOR_REVISION.EDITOR_REVISION_ID.eq(editorRevisionId))
                .fetchOptional(record -> new EditorRevisionDescriptor(
                        record.get(EDITOR_REVISION.EDITOR_DOCUMENT_ID),
                        record.get(EDITOR_REVISION.EDITOR_REVISION_ID),
                        record.get(EDITOR_REVISION.WORKSPACE_ID),
                        record.get(EDITOR_REVISION.REVISION_NO),
                        record.get(EDITOR_REVISION.CONTENT_HASH)));
    }
}
