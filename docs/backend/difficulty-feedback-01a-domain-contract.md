# DIFFICULTY-FEEDBACK-01A 领域合同

状态：Implemented, pending final clean-HEAD regression

## 1. 业务边界

本工作包保存一份粗粒度 1–5 星初判，以及老师不断修正形成的完整历史。它不负责提高模型准确率，也不修改题目内容、Question Review、G5 或搜索投影。

`question_revision.difficulty_stars` 继续作为 legacy imported-content evidence。新反馈域的当前唯一权威是：

```text
question_difficulty_state.current_snapshot_id
```

不得使用 `max(created_at)` 猜测当前难度，也不得因为只修改难度就创建新的 `question_revision`。

## 2. 版本化 Rubric

`difficulty_rubric_version` 冻结：

- `rubric_key` 与 `version_code`；
- subject、stage 和可选 grade；
- 固定 1–5 量尺；
- 每一级非空定义；
- canonical definitions 与 `rubric_hash`；
- active/retired 状态和创建人。

同一 key/version、同 payload 是幂等重放；不同 payload fail closed。版本记录创建后禁止 UPDATE/DELETE；规则调整必须创建新版本。

## 3. 人群上下文

难度不是题目的无条件常量。每个 snapshot 同时冻结 `context_key`、canonical `context_json` 与 `context_hash`，至少要求 subject/stage/grade 与题目一致。相同 `context_key` 再次携带不同上下文会返回 409，防止普通班、拔高班或不同年级的反馈被混合。

state 唯一键为：

```text
(workspace_id, question_revision_id, rubric_key, context_key)
```

## 4. 运行、Snapshot 与反馈

`difficulty_assessment_run` 登记精确模型、prompt profile、证据包、producer/runtime、parameters 与起止时间。同 external run key 同 payload 重放，异 payload 冲突；failed run 可以作为历史观察登记，但不能产出 SYSTEM_SUGGESTION。

`question_difficulty_snapshot` 是完整冻结结果：

- SYSTEM_SUGGESTION：必须引用 completed run，并保存 1–5 值、confidence 与模型上下文；
- HUMAN_FINAL：不引用模型 run；普通确认/纠偏保存 1–5 值；rubric gap 保存 null，不能伪造星级；
- snapshot hash 包含 rubric version、context、score、run、confidence、actor 与模型上下文；
- snapshot 创建后禁止 UPDATE/DELETE。

`question_difficulty_feedback` 保存 before/after snapshot、outcome、reason、note、reviewer/time、client mutation、request hash、expected state version 与确定性操作：

- `DIFFICULTY_CHANGED`；
- `UNCHANGED_CONFIRMED`；
- `RUBRIC_GAP_REPORTED`。

`difficulty_rubric_gap_case` 将“模型判错”与“1–5 规则无法表达”分开。本阶段只创建并在单题历史中读取 open case，不自动修改 rubric。

## 5. 并发与幂等

反馈事务顺序为：业务角色/教学范围校验、mutation advisory lock、同 mutation 重放或冲突、显式 state/before/version 校验、HUMAN snapshot、feedback、CAS、可选 gap、audit、commit。

CAS 使用 `WHERE state_version = expectedStateVersion`。失败事务整体回滚，不留下 snapshot、feedback 或 gap 孤儿行。相同 mutation 与相同 canonical payload 只推进一次 state；同 mutation 不同 payload 返回 409。

## 6. 明确延后

- 将 current difficulty 投影到题目搜索；
- 回填历史 `difficulty_stars`；
- 全局反馈查询与统计分析；
- rubric 管理后台和 gap 治理流程；
- 自动 prompt 优化、在线学习或模型训练；
- 生产 OIDC/session principal 与完整 ACL。

当前 actor 校验只代表 business actor authorization / teaching-scope validation，不代表生产身份认证完成。
