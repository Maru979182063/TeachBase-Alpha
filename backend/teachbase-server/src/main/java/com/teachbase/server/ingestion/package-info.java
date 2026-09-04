/**
 * 中文维护说明：候选题入库编排只调用各模块公开端口；保存待审核内容不等于批准发布。
 * 有界请求在单事务中完成题源、题目和审核任务的写入，重试复用领域幂等身份。
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Candidate Ingestion",
        allowedDependencies = {"question::api", "source::api", "review::api", "fileasset::api"})
package com.teachbase.server.ingestion;
