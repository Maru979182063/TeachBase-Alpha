/**
 * 中文维护说明：难度反馈模块保存版本化评分标准、系统初判、教师终判与当前指针，不改写题目内容 revision。
 */
@org.springframework.modulith.ApplicationModule(
        displayName = "Difficulty Feedback",
        allowedDependencies = {"identity::api", "question::api", "audit::api"})
package com.teachbase.server.difficultyfeedback;
