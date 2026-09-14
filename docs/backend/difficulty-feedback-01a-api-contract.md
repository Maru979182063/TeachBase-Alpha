# DIFFICULTY-FEEDBACK-01A API 合同

Base path：`/api/v1`。所有写接口要求 active workspace member、允许角色和对应 subject/stage teaching scope。

## 1. Rubric

```http
POST /api/v1/difficulty-rubrics/versions
```

提交 `rubricKey`、`versionCode`、subject/stage/grade、1–5 五项文字定义和 status。响应返回 `rubricVersionId`、`rubricHash` 与 replay 标志。同 key/version 不同 payload 返回 409。

## 2. Assessment Run

```http
POST /api/v1/difficulty-assessment-runs
```

保存精确 rubric version、模型/provider/version、prompt profile、证据包 key/version/hash、producer/runtime、parameters 和运行时间。同 external run key 同 payload 重放，异 payload 返回 409。

## 3. SYSTEM_SUGGESTION

```http
POST /api/v1/difficulty-assessment-runs/{runId}/question-suggestions
```

请求包含精确 question revision、`contextKey`、结构化 context、1–5 星、confidence 和模型输出上下文。failed run、retired rubric、题目/rubric/context 不匹配均 fail closed。

第一次 suggestion 创建 pending state；后续 suggestion 只追加历史，不暗中覆盖 current pointer。相同 context key 不允许改变 context payload。

## 4. Review Context

```http
GET /api/v1/question-revisions/{id}/difficulty-review-context
  ?workspaceId=...&actorUserId=...&rubricKey=...&contextKey=...
```

返回 state version/status、最新系统初判、显式 current snapshot、run context 和题目/source 摘要。

## 5. 教师反馈

```http
POST /api/v1/question-revisions/{id}/difficulty-feedback
```

普通确认/纠偏提交 `rubricVersionId`、`contextKey`、`beforeSnapshotId`、`expectedStateVersion`、`clientMutationId`、最终星级、reason 与 note。

尺度缺口提交 `rubricGap.expectedDifficultyText/explanation`，并令最终星级为 null。成功响应返回 feedback ID、replay、最新 state version/status/current snapshot、derived operations 与可选 gap case ID。

过期 state、before snapshot、rubric version 或 context 冲突返回 409，绝不静默覆盖。

## 6. 单题历史

```http
GET /api/v1/question-revisions/{id}/difficulty-feedback-history
  ?workspaceId=...&actorUserId=...&rubricKey=...&contextKey=...
```

返回 SYSTEM/HUMAN snapshots、feedback reason/note/actor/time 和 rubric gap。该接口用于老师回看与审计，不是全局分析 API。
