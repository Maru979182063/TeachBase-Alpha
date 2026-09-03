package com.teachbase.server.fileasset.infrastructure;

import static com.teachbase.jooq.tables.FileAsset.FILE_ASSET;
import static com.teachbase.jooq.tables.FileVersion.FILE_VERSION;

import com.teachbase.server.fileasset.application.FileAssetRepository;
import com.teachbase.server.fileasset.application.FileRegistration;
import com.teachbase.server.fileasset.application.RegisterFileCommand;
import java.time.OffsetDateTime;
import java.util.Optional;
import java.util.UUID;
import org.jooq.DSLContext;
import org.springframework.stereotype.Repository;

@Repository
/**
 * 中文维护说明：本文件属于文件资产模块的数据库或外部工具适配层，负责落实持久化合同；并发正确性最终由事务、锁和数据库约束共同保证。
 *
 * 英文术语对照：jOOQ adapter whose unique constraints arbitrate concurrent checksum registration.
 */
class JooqFileAssetRepository implements FileAssetRepository {

    private final DSLContext database;

    JooqFileAssetRepository(DSLContext database) {
        this.database = database;
    }

    @Override
    public Optional<FileRegistration> findByWorkspaceAndSha256(UUID workspaceId, String sha256) {
        return database.select(
                        FILE_ASSET.FILE_ASSET_ID,
                        FILE_VERSION.FILE_VERSION_ID,
                        FILE_ASSET.WORKSPACE_ID,
                        FILE_ASSET.ORIGINAL_FILENAME,
                        FILE_VERSION.STORAGE_PROVIDER,
                        FILE_VERSION.STORAGE_KEY,
                        FILE_VERSION.MEDIA_TYPE,
                        FILE_VERSION.SIZE_BYTES,
                        FILE_VERSION.SHA256)
                .from(FILE_VERSION)
                .join(FILE_ASSET).on(FILE_ASSET.FILE_ASSET_ID.eq(FILE_VERSION.FILE_ASSET_ID))
                .where(FILE_VERSION.WORKSPACE_ID.eq(workspaceId))
                .and(FILE_VERSION.SHA256.eq(sha256))
                .fetchOptional(record -> new FileRegistration(
                        record.get(FILE_ASSET.FILE_ASSET_ID),
                        record.get(FILE_VERSION.FILE_VERSION_ID),
                        record.get(FILE_ASSET.WORKSPACE_ID),
                        record.get(FILE_ASSET.ORIGINAL_FILENAME),
                        record.get(FILE_VERSION.STORAGE_PROVIDER),
                        record.get(FILE_VERSION.STORAGE_KEY),
                        record.get(FILE_VERSION.MEDIA_TYPE),
                        record.get(FILE_VERSION.SIZE_BYTES),
                        record.get(FILE_VERSION.SHA256),
                        false));
    }

    @Override
    public FileRegistration insert(RegisterFileCommand command) {
        UUID fileAssetId = UUID.randomUUID();
        UUID fileVersionId = UUID.randomUUID();
        OffsetDateTime now = OffsetDateTime.now();
        database.insertInto(FILE_ASSET)
                .set(FILE_ASSET.FILE_ASSET_ID, fileAssetId)
                .set(FILE_ASSET.WORKSPACE_ID, command.workspaceId())
                .set(FILE_ASSET.ORIGINAL_FILENAME, command.originalFilename())
                .set(FILE_ASSET.STATUS, "active")
                .set(FILE_ASSET.CREATED_BY, command.actorUserId())
                .set(FILE_ASSET.CREATED_AT, now)
                .set(FILE_ASSET.UPDATED_AT, now)
                .execute();

        var inserted = database.insertInto(FILE_VERSION)
                .set(FILE_VERSION.FILE_VERSION_ID, fileVersionId)
                .set(FILE_VERSION.FILE_ASSET_ID, fileAssetId)
                .set(FILE_VERSION.WORKSPACE_ID, command.workspaceId())
                .set(FILE_VERSION.VERSION_NO, 1)
                .set(FILE_VERSION.STORAGE_PROVIDER, command.storageProvider())
                .set(FILE_VERSION.STORAGE_KEY, command.storageKey())
                .set(FILE_VERSION.MEDIA_TYPE, command.mediaType())
                .set(FILE_VERSION.SIZE_BYTES, command.sizeBytes())
                .set(FILE_VERSION.SHA256, command.sha256())
                .set(FILE_VERSION.CREATED_BY, command.actorUserId())
                .set(FILE_VERSION.CREATED_AT, now)
                .onConflict(FILE_VERSION.WORKSPACE_ID, FILE_VERSION.SHA256)
                .doNothing()
                .returning(FILE_VERSION.FILE_VERSION_ID)
                .fetchOne();

        if (inserted == null) {
            database.deleteFrom(FILE_ASSET)
                    .where(FILE_ASSET.FILE_ASSET_ID.eq(fileAssetId))
                    .execute();
            return findByWorkspaceAndSha256(command.workspaceId(), command.sha256())
                    .orElseThrow(() -> new IllegalStateException("file_registration_conflict_without_winner"));
        }

        return new FileRegistration(
                fileAssetId,
                fileVersionId,
                command.workspaceId(),
                command.originalFilename(),
                command.storageProvider(),
                command.storageKey(),
                command.mediaType(),
                command.sizeBytes(),
                command.sha256(),
                true);
    }
}
