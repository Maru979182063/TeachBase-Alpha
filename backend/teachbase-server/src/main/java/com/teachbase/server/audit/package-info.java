/**
 * 中文维护说明：本文件属于审计模块的模块边界声明，用于声明模块边界；修改依赖关系时必须同步检查 Spring Modulith 架构测试。
 *
 * 英文术语对照：Append-only business audit events shared through the narrow {@code audit::api} port.
 */
@org.springframework.modulith.ApplicationModule(displayName = "Audit")
package com.teachbase.server.audit;
