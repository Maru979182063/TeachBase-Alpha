package com.teachbase.server.identity.infrastructure;

import static com.teachbase.jooq.tables.WorkspaceMember.WORKSPACE_MEMBER;
import static com.teachbase.jooq.tables.WorkspaceMemberTeachingScope.WORKSPACE_MEMBER_TEACHING_SCOPE;

import com.teachbase.server.identity.api.TeachingScopeResponse;
import com.teachbase.server.identity.application.TeachingScopeRepository;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.jooq.DSLContext;
import org.springframework.stereotype.Repository;

/**
 * 基于 jOOQ 的教学范围仓储；数据库主键和唯一索引负责并发写入的最终裁决。
 */
@Repository
class JooqTeachingScopeRepository implements TeachingScopeRepository {

    private final DSLContext database;

    JooqTeachingScopeRepository(DSLContext database) {
        this.database = database;
    }

    @Override
    public Optional<String> activeMemberRole(UUID workspaceId, UUID userId) {
        return database.select(WORKSPACE_MEMBER.MEMBER_ROLE)
                .from(WORKSPACE_MEMBER)
                .where(WORKSPACE_MEMBER.WORKSPACE_ID.eq(workspaceId))
                .and(WORKSPACE_MEMBER.USER_ID.eq(userId))
                .and(WORKSPACE_MEMBER.STATUS.eq("active"))
                .fetchOptional(WORKSPACE_MEMBER.MEMBER_ROLE);
    }

    @Override
    public boolean lockActiveMember(UUID workspaceId, UUID userId) {
        return database.selectOne()
                .from(WORKSPACE_MEMBER)
                .where(WORKSPACE_MEMBER.WORKSPACE_ID.eq(workspaceId))
                .and(WORKSPACE_MEMBER.USER_ID.eq(userId))
                .and(WORKSPACE_MEMBER.STATUS.eq("active"))
                .forUpdate()
                .fetchOptional()
                .isPresent();
    }

    @Override
    public List<TeachingScopeResponse> findAll(UUID workspaceId, UUID userId) {
        return database.select(
                        WORKSPACE_MEMBER_TEACHING_SCOPE.SUBJECT,
                        WORKSPACE_MEMBER_TEACHING_SCOPE.STAGE,
                        WORKSPACE_MEMBER_TEACHING_SCOPE.IS_PRIMARY)
                .from(WORKSPACE_MEMBER_TEACHING_SCOPE)
                .where(WORKSPACE_MEMBER_TEACHING_SCOPE.WORKSPACE_ID.eq(workspaceId))
                .and(WORKSPACE_MEMBER_TEACHING_SCOPE.USER_ID.eq(userId))
                .orderBy(
                        WORKSPACE_MEMBER_TEACHING_SCOPE.IS_PRIMARY.desc(),
                        WORKSPACE_MEMBER_TEACHING_SCOPE.SUBJECT.asc(),
                        WORKSPACE_MEMBER_TEACHING_SCOPE.STAGE.asc())
                .fetch(record -> new TeachingScopeResponse(
                        record.get(WORKSPACE_MEMBER_TEACHING_SCOPE.SUBJECT),
                        record.get(WORKSPACE_MEMBER_TEACHING_SCOPE.STAGE),
                        Boolean.TRUE.equals(record.get(WORKSPACE_MEMBER_TEACHING_SCOPE.IS_PRIMARY))));
    }

    @Override
    public void replaceAll(
            UUID workspaceId,
            UUID userId,
            UUID actorUserId,
            List<TeachingScopeResponse> scopes) {
        database.deleteFrom(WORKSPACE_MEMBER_TEACHING_SCOPE)
                .where(WORKSPACE_MEMBER_TEACHING_SCOPE.WORKSPACE_ID.eq(workspaceId))
                .and(WORKSPACE_MEMBER_TEACHING_SCOPE.USER_ID.eq(userId))
                .execute();

        for (var scope : scopes) {
            database.insertInto(WORKSPACE_MEMBER_TEACHING_SCOPE)
                    .set(WORKSPACE_MEMBER_TEACHING_SCOPE.WORKSPACE_ID, workspaceId)
                    .set(WORKSPACE_MEMBER_TEACHING_SCOPE.USER_ID, userId)
                    .set(WORKSPACE_MEMBER_TEACHING_SCOPE.SUBJECT, scope.subject())
                    .set(WORKSPACE_MEMBER_TEACHING_SCOPE.STAGE, scope.stage())
                    .set(WORKSPACE_MEMBER_TEACHING_SCOPE.IS_PRIMARY, scope.primary())
                    .set(WORKSPACE_MEMBER_TEACHING_SCOPE.ASSIGNED_BY, actorUserId)
                    .execute();
        }
    }
}
