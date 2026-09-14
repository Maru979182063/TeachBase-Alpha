package com.teachbase.server.identity.infrastructure;

import static com.teachbase.jooq.tables.Workspace.WORKSPACE;
import static com.teachbase.jooq.tables.WorkspaceMember.WORKSPACE_MEMBER;
import static com.teachbase.jooq.tables.WorkspaceMemberTeachingScope.WORKSPACE_MEMBER_TEACHING_SCOPE;

import com.teachbase.server.identity.api.WorkspaceDirectory;
import java.util.UUID;
import java.util.Optional;
import org.jooq.DSLContext;
import org.springframework.stereotype.Repository;

@Repository
/**
 * 中文维护说明：本文件属于工作空间与成员身份模块的数据库或外部工具适配层，负责落实持久化合同；并发正确性最终由事务、锁和数据库约束共同保证。
 *
 * 英文术语对照：Read-only jOOQ adapter for workspace existence and active membership checks.
 */
class JooqWorkspaceDirectory implements WorkspaceDirectory {

    private final DSLContext database;

    JooqWorkspaceDirectory(DSLContext database) {
        this.database = database;
    }

    @Override
    public boolean exists(UUID workspaceId) {
        return database.fetchExists(
                database.selectOne()
                        .from(WORKSPACE)
                        .where(WORKSPACE.WORKSPACE_ID.eq(workspaceId))
                                .and(WORKSPACE.STATUS.eq("active")));
    }

    @Override
    public boolean isActiveMember(UUID workspaceId, UUID userId) {
        return database.fetchExists(
                database.selectOne()
                        .from(WORKSPACE_MEMBER)
                        .where(WORKSPACE_MEMBER.WORKSPACE_ID.eq(workspaceId))
                        .and(WORKSPACE_MEMBER.USER_ID.eq(userId))
                        .and(WORKSPACE_MEMBER.STATUS.eq("active")));
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
    public boolean hasTeachingScope(
            UUID workspaceId, UUID userId, String subject, String stage) {
        return database.fetchExists(
                database.selectOne()
                        .from(WORKSPACE_MEMBER_TEACHING_SCOPE)
                        .where(WORKSPACE_MEMBER_TEACHING_SCOPE.WORKSPACE_ID.eq(workspaceId))
                        .and(WORKSPACE_MEMBER_TEACHING_SCOPE.USER_ID.eq(userId))
                        .and(WORKSPACE_MEMBER_TEACHING_SCOPE.SUBJECT.eq(subject))
                        .and(WORKSPACE_MEMBER_TEACHING_SCOPE.STAGE.eq(stage)));
    }
}
