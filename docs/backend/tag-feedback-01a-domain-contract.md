# TAG-FEEDBACK-01A 领域合同

状态：Implemented, pending full regression evidence
适用范围：教师标签反馈采集核心，不包含标签检索投影、旧 writer fencing 或生产身份认证。

## 1. 目标与边界

本工作包只保证从第一笔教师修改开始，以下事实可被完整追溯：

- 精确模型运行上下文；
- 模型对精确 `question_revision` 的完整标签原判；
- 教师提交的完整终判标签集合；
- 原判与终判之间的确定性差异；
- 原因、备注、教师、提交时间与 mutation identity；
- taxonomy 中没有合适节点时的独立 gap case；
- 当前标签集合的唯一显式指针。

标签反馈不创建或修改 `question_revision`，不调用 Question Review writer，不更新 `question.approved_revision_id`，也不更新 `question_taxonomy_link`。

## 2. 三层事实

| 层 | 数据 | 语义 |
| --- | --- | --- |
| 历史事实 | `tagging_run`、`question_tag_snapshot`、`question_tag_snapshot_item`、`question_tag_feedback`、`taxonomy_gap_case` | 追加后不可篡改的运行、标签集合与反馈证据 |
| 当前权威 | `question_tag_state.current_snapshot_id` | 新标签反馈域唯一 current authority；禁止按 `max(created_at)` 推断 |
| 旧证据 | `question_taxonomy_link`、`question_revision.primary_knowledge_tag`、`secondary_knowledge_tags_json` | legacy/import assignment 与导入时内容快照，不是 HUMAN_FINAL authority |

`question_taxonomy_link` 的 current projection、旧 writer fencing 和 Question Search 切换全部属于 01B。

## 3. 六张表

### `tagging_run`

登记一份已结束的模型运行观察。01A 接口只接受 `completed` 或 `failed`，整行通过 trigger 禁止 UPDATE/DELETE。稳定键是 `(workspace_id, external_run_key)`：同 key、同 `run_hash` 为重放；同 key、不同 hash 返回冲突。

`canonical_import_request_id` 只是一条可空来源引用。Tagging Run 与 G5 Import Request 生命周期不同，不能互相替代。

### `question_tag_snapshot` / `question_tag_snapshot_item`

Snapshot 是精确题目 revision、精确 taxonomy version 下的完整标签集合，不是 patch：

- `SYSTEM_SUGGESTION` 必须引用精确 `tagging_run_id`；
- `HUMAN_FINAL` 不伪造模型 run；
- 普通 HUMAN_FINAL 由服务强制恰好一个 primary；
- taxonomy gap 的 HUMAN_FINAL 允许零 primary，且 state 必须进入 `taxonomy_gap`；
- item 具有 taxonomy node FK、relation、position、confidence 和 candidate rank；
- partial unique index 保证一个 snapshot 至多一个 primary；
- `item_count`、插入 guard 与 deferred completeness trigger 保证提交后不能追加 item，也不能提交残缺 snapshot；
- snapshot 与 item 均禁止 UPDATE/DELETE。

### `question_tag_feedback`

一条教师行为事实，保存 before/after snapshot、outcome、reason、note、actor/time、`client_mutation_id`、request hash、提交时看到的 state version 和派生 diff。整行禁止 UPDATE/DELETE。

`derived_operations_json` 是可重新计算缓存；before/after snapshot 才是历史事实。

### `question_tag_state`

唯一键为 `(workspace_id, question_revision_id, taxonomy_key)`。状态包括：

```text
pending -> reviewed
pending/reviewed -> taxonomy_gap
任何不兼容版本切换 -> needs_reconciliation（01A 只保留状态，不实现治理流程）
```

所有教师提交使用 `WHERE state_version = expectedStateVersion` 的 compare-and-set。成功原子加一；失败返回 409，整个事务回滚。

### `taxonomy_gap_case`

gap 与 model wrong 分开保存。01A 只创建并在单题历史中读取 `open` case；不自动建 node、不修改 taxonomy、不做自动映射。后续治理可使用 `triaged/resolved/rejected` 字段，但不属于本工作包 API。

## 4. 双 Hash

### `labelSetHash`

canonical payload 只包含：

```json
{
  "taxonomyVersionId": "uuid",
  "primaryNodeId": "uuid-or-null",
  "secondaryNodeIds": ["sorted-distinct-uuid"]
}
```

对象键排序；secondary 按 UUID 字符串排序；JSON whitespace、对象键顺序、secondary 输入顺序不改变结果。

### `snapshotHash`

在 `labelSetHash` 之外冻结：snapshot kind、tagging run identity、创建 actor、canonical model output context，以及每个 item 的 relation、position、confidence 和 candidate rank。数字使用去除无意义尾零后的十进制 canonical form。

因此相同标签集合在不同 run 或不同 confidence 下保持相同 `labelSetHash`，但具有不同 `snapshotHash`。

## 5. 并发与幂等顺序

反馈事务按以下顺序执行：

```text
业务成员/教学范围校验
-> canonical request hash
-> workspace + clientMutationId advisory transaction lock
-> 已有 mutation：同 payload 重放 / 异 payload 409
-> 读取显式 state
-> 校验 beforeSnapshot、taxonomyVersion、expectedStateVersion
-> 创建或复用 HUMAN_FINAL snapshot
-> 写 feedback
-> state compare-and-set
-> 可选 gap case
-> append-only audit event
-> commit
```

任何一步失败均回滚本事务创建的 snapshot、feedback 和 gap。相同 mutation 的重试返回第一次成功的 feedback、after snapshot 和结果版本，不重复推进 state。

## 6. 自动 Diff

当前稳定操作码：

- `PRIMARY_CHANGED`
- `PRIMARY_SECONDARY_SWAP`
- `SECONDARY_ADDED`
- `SECONDARY_REMOVED`
- `UNCHANGED_CONFIRMED`

输入永远是完整 before/after 集合，输出按固定规则与 UUID 顺序生成。教师无需手填操作类型。

## 7. 权限与隔离

01A 验证 active workspace member、`owner/admin/editor/reviewer` role，以及与题目 subject/stage 精确匹配的 teaching scope。查询外部 workspace 的已知 ID 与随机 ID 返回相同资源缺失结果，避免实体枚举。

这只是 **business actor authorization / scope validation**。`actorUserId` 仍来自请求参数，不是 OIDC/session principal，因此不得声称生产级身份认证完成。

## 8. 真实模型适配

稳定测试摘录位于 `tests/fixtures/tag_feedback/real_math_case054_model_excerpt.json`。它来自实际 `case_054.tagging_trace.json`，保留源 SHA-256、模型、运行版本、主标签外部键、`0.82` confidence、candidate rank 9 和模型决策上下文；加密推理正文和本机绝对路径未进入仓库。

原 trace 没有正式 prompt manifest，因此适配明确登记为 `legacy-unversioned:model_trace_case054_confidence_v02`，不伪造不存在的 prompt 版本。

## 9. 明确延后

01B 或更后续处理：`question_taxonomy_link` current projection、旧 writer fencing、Question Search current tag、taxonomy picker、全局反馈查询、JSONL export、历史回填、多 primary 治理、inherited candidate、analytics、统一搜索、自动 prompt/训练/taxonomy 修改、gap 发布规则、OIDC 与完整 ACL。

`BLOCKS_TAG_SCHEMA_AND_SEARCH` 继续保持开放。
