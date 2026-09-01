/**
 * 中文维护说明：本文件属于题篮与快照模块的模块边界声明，用于声明模块边界；修改依赖关系时必须同步检查 Spring Modulith 架构测试。
 * Owns question baskets, optimistic draft saves, recoverable checkpoints, and
 * immutable publication snapshots. It pins concrete question revisions through the
 * question module's public API.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Question Collections",
        allowedDependencies = {"identity::api", "question::api", "audit::api"})
package com.teachbase.server.collection;
