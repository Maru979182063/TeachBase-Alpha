/**
 * 中文维护说明：统一内容导入模块只拥有 package ledger、DAG、lease 与恢复编排；
 * Question、Module、Editor、Handout 正文仍由各自领域模块拥有。
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Canonical Content Import",
        allowedDependencies = {
                "identity::api", "audit::api", "fileasset::api", "source::api",
                "question::api", "standardmodule::api", "editor::api", "handout::api",
                "taxonomy::api", "review::api"
        })
package com.teachbase.server.canonicalimport;
