/**
 * 中文维护说明：本文件属于题源证据模块的模块边界声明，用于声明模块边界；修改依赖关系时必须同步检查 Spring Modulith 架构测试。
 *
 * 英文术语对照：Owns original teaching-source evidence and addressable source regions.
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Source Evidence",
        allowedDependencies = {"identity::api", "audit::api"})
package com.teachbase.server.source;
