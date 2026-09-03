/**
 * 中文维护说明：本文件属于文件资产模块的模块边界声明，用于声明模块边界；修改依赖关系时必须同步检查 Spring Modulith 架构测试。
 *
 * 英文术语对照：Owns portable file identities, immutable byte versions, hashes, and storage keys.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "File Assets",
        allowedDependencies = {"identity::api", "audit::api"})
package com.teachbase.server.fileasset;
