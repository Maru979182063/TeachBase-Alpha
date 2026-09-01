/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，用于声明模块边界；修改依赖关系时必须同步检查 Spring Modulith 架构测试。
 * Owns canonical editor documents, immutable revisions, audience projection, and
 * export-ready snapshots. Browser interaction and visual layout remain frontend concerns.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Editor Content",
        allowedDependencies = {"identity::api", "question::api", "audit::api"})
package com.teachbase.server.editor;
