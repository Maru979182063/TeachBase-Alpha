package com.teachbase.server.editor.application;

/**
 * 中文维护说明：旧客户端仍提交 expectedRevisionNo 时明确要求升级，避免在灰度切换期被误判为普通参数错误。
 */
public class EditorClientUpgradeRequiredException extends RuntimeException {

    public EditorClientUpgradeRequiredException() {
        super("editor_client_contract_upgrade_required");
    }
}
