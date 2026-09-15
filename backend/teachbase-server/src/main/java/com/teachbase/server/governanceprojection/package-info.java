/**
 * 中文维护说明：治理投影模块只把 Tag/Difficulty 当前权威状态搬运为可重建读模型，绝不反写治理事实。
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Governance Projection",
        allowedDependencies = {"identity::api"})
package com.teachbase.server.governanceprojection;
