/**
 * 中文维护说明：本文件属于在线编辑文档模块的模块边界声明，用于声明模块边界；修改依赖关系时必须同步检查 Spring Modulith 架构测试。
 * 中文维护说明：本模块拥有规范编辑文档、不可变修订、受众投影与可导出快照；浏览器交互和视觉布局仍由前端负责。
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Editor Content",
        allowedDependencies = {"identity::api", "question::api", "audit::api"})
package com.teachbase.server.editor;
