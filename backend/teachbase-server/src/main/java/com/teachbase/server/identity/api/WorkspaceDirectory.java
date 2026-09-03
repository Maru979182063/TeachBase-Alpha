package com.teachbase.server.identity.api;

import java.util.UUID;

/**
 * 中文维护说明：本文件属于工作空间与成员身份模块的对外稳定合同层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Minimal tenant authorization lookup shared without exposing identity persistence.
 */
public interface WorkspaceDirectory {

    boolean exists(UUID workspaceId);

    boolean isActiveMember(UUID workspaceId, UUID userId);
}
