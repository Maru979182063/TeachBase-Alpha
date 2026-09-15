package com.teachbase.server.governanceprojection.application;

/** 中文维护说明：对外统一隐藏 workspace 不存在、非成员和无维护权限三类细节。 */
public class GovernanceProjectionAccessException extends RuntimeException {
    public GovernanceProjectionAccessException() {
        super("governance_projection_access_denied");
    }
}
