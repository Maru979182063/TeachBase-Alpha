/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，用于声明模块边界；修改依赖关系时必须同步检查 Spring Modulith 架构测试。
 * Owns explicit human review cases and append-only decisions. Question content is
 * never edited here; the module can only publish a frozen revision through the
 * Questions public review gateway.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Review",
        allowedDependencies = {"identity::api", "question::api", "audit::api"})
package com.teachbase.server.review;
