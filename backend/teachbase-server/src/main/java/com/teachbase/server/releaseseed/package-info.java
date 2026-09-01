/**
 * 中文维护说明：本文件属于首发数据包导入模块的模块边界声明，用于声明模块边界；修改依赖关系时必须同步检查 Spring Modulith 架构测试。
 * Orchestrates validated Release Seed packages through public domain-module ports.
 * It owns checkpoints only and never writes question, review, taxonomy, file, or
 * source tables directly.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Release Seed",
        allowedDependencies = {
            "identity::api", "audit::api", "fileasset::api", "source::api",
            "question::api", "review::api", "taxonomy::api"
        })
package com.teachbase.server.releaseseed;
