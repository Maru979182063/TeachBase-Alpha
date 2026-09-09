/**
 * 中文维护说明：标准模块是与题目同级的一等内容资产；稳定身份、不可变修订、审核和来源均由本模块负责。
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Standard Modules",
        allowedDependencies = {"identity::api", "audit::api"})
package com.teachbase.server.standardmodule;
