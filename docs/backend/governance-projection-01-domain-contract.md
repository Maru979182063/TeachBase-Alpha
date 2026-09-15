# Governance Projection 01 Domain Contract

## 四层边界

### FACT AUTHORITY

- Tag facts: immutable `question_tag_snapshot`、snapshot item、feedback。
- Difficulty facts: immutable rubric/run/snapshot/feedback。
- 投影器没有这些表的写入口，也不修改 Question Revision。

### CURRENT AUTHORITY

- Tag: `question_tag_state.current_snapshot_id` 与 `state_version`。
- Difficulty: `question_difficulty_state.current_snapshot_id` 与 `state_version`。
- state 更新与 outbox trigger 在同一 PostgreSQL 事务提交。

### PROJECTION

- `question_tag_current_projection` 与规范化 secondary 子表。
- `question_difficulty_current_projection`。
- `governance_projection_outbox`。
- Projection 是搬运工，不是裁判。它只复制 authority 已明确提交的完整结果。
- 同版本同 hash 是幂等 replay；低版本不得覆盖高版本；同版本不同 hash fail closed。
- 投影全部丢失时，只从 CURRENT AUTHORITY 做 full rebuild。

### LEGACY FALLBACK

- `question_revision.primary_knowledge_tag`、`secondary_knowledge_tags_json`、
  `difficulty_stars` 是历史导入和旧搜索证据。
- V013 不读取、覆盖或反写这些字段。
- 无 current authority 的旧题目保持无投影，不宣称为 HUMAN_FINAL。

## 一致性与恢复

1. mutation 提交事实、current state 和 outbox event。
2. worker 使用 `FOR UPDATE SKIP LOCKED` 领取短租约。
3. worker 按 state id 重读当前 authority，不信任 event 中的事实副本。
4. 投影 upsert 由 `authority_state_version` 防倒灌。
5. 成功后 event 标记 processed；失败则保留 failed 并延迟 retry。
6. worker 中断后，过期 processing lease 可被新进程重新领取。
7. workspace rebuild 在同一事务共享锁 authority state，清空并重建该 workspace 投影。

投影失败不会删除 snapshot/feedback，不会回滚已提交的教师修改，也不会创建 Question Revision。

## 查询边界

本工作包只支持 PostgreSQL 精确条件：workspace、subject、stage、taxonomy key、主标签、
副标签、rubric、difficulty context 和 difficulty value。它不是 unified search、全文搜索、
语义搜索、推荐或统计平台。

`BLOCKS_TAG_SCHEMA_AND_SEARCH` 保持 OPEN。本投影不决定“旧主标签降为副标签还是删除”，
只呈现 current authority 的最终 primary/secondary 集合。
