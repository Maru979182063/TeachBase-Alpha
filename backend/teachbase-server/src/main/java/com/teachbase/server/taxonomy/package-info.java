/**
 * 中文维护说明：本文件属于知识体系版本模块的模块边界声明，用于声明模块边界；修改依赖关系时必须同步检查 Spring Modulith 架构测试。
 * Owns versioned knowledge-point trees, aliases, and assignments to immutable
 * question revisions. Difficulty policy is intentionally outside this module.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Taxonomy",
        allowedDependencies = {"identity::api", "question::api", "audit::api"})
package com.teachbase.server.taxonomy;
