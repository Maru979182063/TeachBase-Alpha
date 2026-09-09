/**
 * 中文维护说明：讲义模块拥有 edition、统一 composition、occurrence 和精确 artifact 关系，
 * 不拥有题目或标准模块正文。
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Handout Composition",
        allowedDependencies = {
                "identity::api", "editor::api", "question::api", "standardmodule::api", "audit::api"
        })
package com.teachbase.server.handout;
