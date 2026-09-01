/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，用于声明模块边界；修改依赖关系时必须同步检查 Spring Modulith 架构测试。
 * Converts frozen editor snapshots into durable files through a leased PostgreSQL
 * work queue. It never reads mutable editor drafts during rendering.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Exports",
        allowedDependencies = {"identity::api", "editor::api", "fileasset::api", "audit::api"})
package com.teachbase.server.exporting;
