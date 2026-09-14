/**
 * 中文维护说明：标签反馈模块只保存模型原判、教师终判与当前指针，不修改题目 revision、Review 或旧 taxonomy link。
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Tag Feedback",
        allowedDependencies = {"identity::api", "question::api", "taxonomy::api", "audit::api"})
package com.teachbase.server.tagfeedback;
