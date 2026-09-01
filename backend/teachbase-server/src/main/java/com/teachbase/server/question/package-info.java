/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，用于声明模块边界；修改依赖关系时必须同步检查 Spring Modulith 架构测试。
 * Owns stable question identities, immutable content revisions, review visibility,
 * provenance, and indexed retrieval. Collections and editors consume only its public
 * revision directory so they cannot couple to question persistence internals.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Questions",
        allowedDependencies = {"identity::api", "audit::api"})
package com.teachbase.server.question;
