# GOVERNANCE-PROJECTION-01 Design Audit

## 审计基线

- Branch: `backend/g5-canonical-content-import-recovery`
- HEAD: `46a6cb1b9dc4b4d44edcdc2e80efc79578b2142b`
- 审计结论：不存在必须修改事实层语义的 authority conflict，可以继续实施。

## 真实 Authority

### Tag

- 不可变事实：`question_tag_snapshot`、`question_tag_snapshot_item`、`question_tag_feedback`。
- 当前权威：`question_tag_state.current_snapshot_id`。
- 单调版本：`question_tag_state.state_version`。
- 稳定维度：`workspace_id + question_revision_id + taxonomy_key`。
- 投影必须只跟随 state 指向的 snapshot，不能按时间猜测，也不能读取
  `question_taxonomy_link` 或 legacy 文本冒充 HUMAN_FINAL。

### Difficulty

- 不可变事实：`difficulty_rubric_version`、`difficulty_assessment_run`、
  `question_difficulty_snapshot`、`question_difficulty_feedback`。
- 当前权威：`question_difficulty_state.current_snapshot_id`。
- 单调版本：`question_difficulty_state.state_version`。
- 稳定维度：`workspace_id + question_revision_id + rubric_key + context_key`。
- `rubric_version_id`、`context_key` 和 `context_hash` 都是正式语义，不能退化为
  `question_revision.difficulty_stars`。

## Legacy 消费路径

- `JooqQuestionRepository` 的既有题目搜索仍读取
  `question_revision.primary_knowledge_tag` 和 `difficulty_stars`。
- `question_taxonomy_link` 仍服务既有 taxonomy/release seed 合同。
- 本工作包新增独立治理查询 API，不覆盖上述字段，不改变旧搜索行为。

## 投影设计

- `question_tag_current_projection` 保存一条 taxonomy 维度的当前标签投影。
- `question_tag_current_projection_secondary` 规范化保存副标签，支持节点索引查询。
- `question_difficulty_current_projection` 保存 rubric/context 维度的当前难度投影。
- 每条投影保存 authority state version 和 semantic hash；相同版本幂等，旧版本不能覆盖新版本。
- 投影表启用数据库 writer guard，只有投影事务显式设置本地 writer 标记后才能修改。

## Outbox 与恢复

- `governance_projection_outbox` 使用 PostgreSQL 租约、`FOR UPDATE SKIP LOCKED`、
  可重试失败状态和稳定 event key。
- V013 trigger 在 authority state INSERT/UPDATE 的同一事务写 outbox，避免修改已验收的
  Tag/Difficulty 服务事务语义，也覆盖未来的其他合法 writer。
- event 只携带 authority 指针和版本；projector 始终重新读取当前 state/snapshot。
- 现有 export/release-seed worker 提供了租约模式参考，但不适合复用其业务表；本工作包
  复用同一 PostgreSQL lease/recovery 模式，不建立第二套通用任务平台。

## Full Rebuild

- rebuild 只扫描两个 authority state 及其精确 snapshot。
- workspace rebuild 在事务内锁定对应 state，删除并重建投影。
- rebuild 不读取投影、legacy 字段或历史最大时间。
- `projected_at` 可变化，其余 canonical 字段由 semantic hash 校验增量与重建相等。

## 保持开放

- `BLOCKS_TAG_SCHEMA_AND_SEARCH` 保持 OPEN；投影只搬运完整终态，不决定旧主标签降级或删除。
- unified/fuzzy/semantic search、推荐、统计平台、模型和 prompt 优化均不在本工作包。
- 生产认证与完整 ACL 仍为独立开放门禁；本工作包沿用 workspace member/role 边界。
