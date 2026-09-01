/**
 * 中文维护说明：本文件属于旧数据迁移隔离模块的模块边界声明，用于声明模块边界；修改依赖关系时必须同步检查 Spring Modulith 架构测试。
 *
 * 英文术语对照：Isolates restartable legacy imports and old-to-new identifier mapping.
 */
@org.springframework.modulith.ApplicationModule(displayName = "Legacy Migration")
package com.teachbase.server.migration;
