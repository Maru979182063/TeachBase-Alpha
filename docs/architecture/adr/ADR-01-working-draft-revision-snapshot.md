# ADR-01 Working Draft / Revision / Snapshot

- 状态：Accepted，WP-01 已实现
- 日期：2026-09-02
- 范围：在线讲义编辑态、恢复点、正式版本、预览确认与导出快照

## 背景

旧 `editor_draft` 只是指向最新 `editor_revision` 的可变游标，每次 PUT 都先创建永久 revision。它能阻止静默覆盖，但把高频自动保存、恢复点和正式历史混成了一层。WP-01 将浏览器编辑态分离为每文档唯一的 working draft，既有 revision、snapshot 和 export 继续作为不可变交付边界。

## 三类对象

| 对象 | 可变 | 用途 | 保留 |
| --- | --- | --- | --- |
| working draft | 是 | 当前浏览器编辑真相 | 文档存在期间保留 |
| checkpoint | 否 | 短期恢复 | 按类型 TTL 和数量策略清理 |
| immutable revision | 否 | 明确业务事件形成的正式历史 | 永久或按归档政策 |
| snapshot | 否 | 已确认 variant/audience 的导出输入 | 永久或按交付政策 |

每个 editor document 最多有一行 working draft：

```text
document_id
base_revision_id
draft_version
content_json
content_hash
content_bytes
updated_by
updated_at
```

`content_json` 保存 `editorModel`、`schemaVersion`、`masterDoc` 和 `versionOverrides`。`base_revision_id` 可为空，或精确指向当前草稿最近一次复用/冻结的 revision；它不是 latest 指针。

## Autosave 与并发

所有修改使用 compare-and-set：

```sql
update editor_working_draft
   set draft_version = draft_version + 1, ...
 where editor_document_id = :documentId
   and workspace_id = :workspaceId
   and draft_version = :expectedDraftVersion;
```

- affected rows 为 0 返回 HTTP 409，响应包含 `currentDraftVersion`；不得覆盖当前内容。
- 每个 autosave 必须携带最多 128 字符的 `clientMutationId`。
- 幂等作用域是 `(workspace_id, editor_document_id, client_mutation_id)`，数据库唯一约束负责最终裁决。
- 幂等记录保留 7 天，并保存原请求 expected version、首次成功结果的 draft version、content、hash 和 base revision。
- 过期幂等记录按 `(expires_at, editor_autosave_mutation_id)` 索引分批删除；默认每批 5000 行，清理可重试。
- 相同 key、expected version 和 content hash 的重试返回首次成功结果，不增加 draft version，不建 checkpoint/revision，也不产生虚假 409。
- 相同 key 被不同请求复用返回 409 `editor_client_mutation_conflict`。

普通 autosave 绝不创建 `editor_revision`。

## Checkpoint 策略

- 前端建议脏数据 debounce 2 秒，持续输入最多每 15 秒发送一次 autosave。
- 服务端每文档每 2 分钟最多创建一个 `autosave` checkpoint。
- `autosave` checkpoint TTL 为 72 小时，每文档最多保留最近 100 个。
- `conflict_recovery` 保留 7 天；`pre_transition` 保留 30 天。
- 初期保存完整 JSON，不使用增量 diff。
- checkpoint 只用于恢复，不进入正式版本历史。
- 清理任务可重复运行；过期或超量 checkpoint 可删除，但每文档最新恢复点、working draft、revision 和 snapshot 永远不删除。

## Immutable Revision 事件

只有以下显式事件可以创建 immutable revision：

1. 用户手动创建版本点；
2. 提交审核；
3. preview confirmation；
4. 正式发布所需冻结。

受控导入走 ingestion 的独立 revision 合同，不伪装成 autosave。普通 autosave 和 checkpoint 不得创建 revision。

## Preview Confirmation

规则固定为：

```text
若 working draft content_hash 与可复用 immutable revision 相同
  -> 复用该 revision
否则
  -> 创建 exactly one immutable revision
```

随后 confirmation 与 snapshot 都固定精确 `editor_revision_id`。snapshot 保存投影后的完整内容、revision、variant key、audience、schema version 和 hash；导出只读取 snapshot。相同内容重复确认可以创建不同 audience/variant snapshot，但不得无限创建相同 revision。

## 迁移与 Writer Fencing

执行顺序固定为：

```text
expand
-> backfill
-> dual-read compatibility
-> writer fencing
-> new writer switch
-> verification
-> contract later
```

V008 仅执行 expand：增加 working draft、mutation、checkpoint、`writer_mode` 和数据库 writer-fence trigger，不删除或回填旧表。

1. 先部署理解 `writer_mode` 的版本，保持新 writer 开关关闭，并排空更老实例。
2. backfill 或首次打开在文档行锁内读取当时的 `editor_draft -> editor_revision`，写 working draft 后切换 `writer_mode=working_draft`。
3. 旧 writer 与 backfill 都锁 `editor_document`；切换后数据库 trigger 拒绝任何旧 `editor_draft` INSERT/UPDATE/DELETE，旧事务整体回滚。触发器使用专用 SQLSTATE `TB001`，便于应用和告警从普通数据库错误中准确识别 writer fence。
4. 未迁移文档首次打开可懒迁移；重复 backfill 对已切换文档无动作。
5. rollout 进程重启后根据持久化 `writer_mode` 继续，不依赖进程内状态；批量工具按文档提交，可断点续跑。
6. feature flag `TEACHBASE_EDITOR_WORKING_DRAFT_ENABLED` 控制新 writer，`TEACHBASE_EDITOR_LAZY_MIGRATION_ENABLED` 控制按需迁移。不得让旧 writer 与新 writer 长期并写。

旧客户端如果仍发送 `expectedRevisionNo`，HTTP 层返回 426 `editor_client_contract_upgrade_required`，不把 revision no 猜成 draft version。上线顺序必须先发布理解 `expectedDraftVersion/clientMutationId` 的客户端，再启用新 writer；关闭 feature flag 时所有新写请求返回 503，读取已迁移 working draft 不受影响。

`trg_fence_legacy_editor_draft_writer` 只能在旧 writer、回滚窗口和旧 `editor_draft` 兼容读取全部退役后的独立 contract migration 中删除。该迁移应显式执行 `drop trigger` 和 `drop function`；WP-01 不提前移除最后一道数据库防线。

## 回滚

回滚不能只停写新表。切回旧应用前必须运行：

```bash
TEACHBASE_EDITOR_WRITES_DRAINED=true node tools/editor_working_draft_maintenance.mjs rollback-materialize [document-id...]
```

工具对每个文档开启独立事务并加行锁：按 content hash 复用 revision，或创建 exactly one 兼容 revision；随后先切 `writer_mode=legacy`，再更新/创建旧 `editor_draft` pointer。由此只存在于 working draft 的最后成功内容会进入旧 writer 可读结构。工具可重复执行，已处于 legacy 的文档直接跳过。

维护工具的并发边界是明确的运维栅栏：执行批量 backfill 或 rollback materialization 前必须停止 editor 写流量并排空应用实例，并显式设置 `TEACHBASE_EDITOR_WRITES_DRAINED=true`，否则命令拒绝运行。该确认变量不能替代真实排流量。文档行锁保证工具自身、懒迁移和确认事务不会互相覆盖，但它不能替代“回滚过程中禁止新 writer 再次写入”的部署纪律。中途中断可按文档断点重跑；单文档事务要么完整提交，要么完整回滚。

再次启用前可运行 `backfill`；若 working draft 行仍存在，则用 legacy writer 最后成功内容覆盖并增加 draft version，避免恢复陈旧草稿。

## 恢复与观测

- 服务崩溃后以数据库已提交 working draft 为准。
- checkpoint 恢复必须形成新的 CAS draft version，不能改历史 checkpoint。
- audit 事件记录 `editor_working_draft.autosaved`、draft version、mutation ID 和 content hash；幂等重试不重复记一次业务保存。
- HTTP 409 区分 draft version 冲突与 mutation key 冲突；writer fence 返回 503，便于 rollout 告警。
- 运行 gate 报告 autosave、冲突、checkpoint、迁移、fence 和 rollback 结果，不把本机绝对路径当合同。
- `content_bytes`、`content_hash`、`draft_version` 和 `updated_at` 是草稿体积与热度观测字段。`content_json` 不建 GIN 等内容索引，PostgreSQL 使用 TOAST 存放大 JSON；每次全量 autosave 仍会产生新 tuple、TOAST 写入和 WAL。
- 运维应观察 `pg_stat_user_tables.n_tup_upd/n_dead_tup/last_autovacuum`、表及 TOAST 大小、WAL 增速、保存延迟和 409 比例。working draft 使用 fillfactor 80，热更新表采用更低 autovacuum/analyze scale factor；这降低膨胀风险，但不承诺无限文档大小。

## 不采用

- 不再接受每次 autosave 创建永久 revision。
- 不用 snapshot 充当恢复点。
- 不在 WP-01 删除旧 editor 表、压缩旧 revision 或改写历史 snapshot。
