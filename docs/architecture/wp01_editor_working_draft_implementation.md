# WP-01 Editor Working Draft Separation

## 范围与结果

WP-01 只拆分在线编辑器的可变 working draft、短期 checkpoint 与 immutable revision。它复用现有 `editor_document`、三版本、validator、revision、preview confirmation、snapshot、export 和 workspace 审计合同，没有创建第二套 editor。

本工作包没有实现 standard module、统一搜索、knowledge document、question group、OIDC，也没有修改四条生产链内部。

## 数据库迁移

正式追加迁移是 `V008__editor_working_draft_separation.sql`：

| 变更 | 作用 |
| --- | --- |
| `editor_document.writer_mode` | 持久化每文档 writer fence 状态 |
| `editor_working_draft` | 每文档唯一可变内容、draft version、base revision |
| `editor_autosave_mutation` | 7 天幂等结果，唯一键为 workspace/document/mutation，按到期时间分批清理 |
| `editor_draft_checkpoint` | 短期完整 JSON 恢复点 |
| legacy writer trigger | working-draft 模式下拒绝旧 `editor_draft` 写入 |

V008 是根据现有组合外键、workspace member、审计与 jOOQ DDL generation 重新编写的 expand migration，不是复制 Phase 0 spike。它不删除、不改写、不回填既有 revision/snapshot/export。

真实 PostgreSQL 迁移门禁分别执行空库 `V001 -> V008` 与带 revision、draft、preview confirmation、snapshot 数据的 `V007 -> V008`。升级前后历史行按完整行内容比较一致；新表为空、旧文档保持 `writer_mode=legacy`，证明 V008 是纯追加而不是隐式回填。

## API 合同

### 创建文档

`POST /api/v1/editor/documents`

- 创建 working draft version 1。
- 新文档不创建 immutable revision，`baseRevisionId=null`、`baseRevisionNo=0`。
- ETag 为 `"draft-1"`。

### 读取草稿

`GET /api/v1/editor/documents/{documentId}/draft?workspaceId=...&actorUserId=...`

- 返回 `draftVersion`、`baseRevisionId/baseRevisionNo`、结构化内容与 hash。
- 未迁移旧文档在 feature flag 允许时进行事务性懒迁移。
- workspace 不匹配返回 404，不泄漏其他 workspace 的对象是否存在。

### 自动保存

`PUT /api/v1/editor/documents/{documentId}/draft`

```json
{
  "workspaceId": "uuid",
  "actorUserId": "uuid",
  "expectedDraftVersion": 12,
  "clientMutationId": "browser-session-7:mutation-42",
  "schemaVersion": 1,
  "masterDoc": {},
  "versionOverrides": [null, null, null]
}
```

- 成功返回 version 13 和 `ETag: "draft-13"`。
- 相同 mutation 重试返回首次结果并设置 `idempotentReplay=true`。
- CAS 冲突返回 409 `editor_draft_version_conflict` 与 `currentDraftVersion`。
- key 被不同请求复用返回 409 `editor_client_mutation_conflict`。
- writer 关闭或被隔离返回 503 `editor_writer_fenced`。
- 仍发送 `expectedRevisionNo` 的旧客户端返回 426 `editor_client_contract_upgrade_required`；服务不会猜测旧 revision no 等于新 draft version。

### 题目落位

`POST /api/v1/editor/documents/{documentId}/question-references`

同样使用 `expectedDraftVersion` 和 `clientMutationId`。autosave 内容中保存精确 `questionRevisionId`；正式关系索引在 preview confirmation 冻结 revision 时建立，避免把可变草稿伪装成发布引用。

### Preview Confirmation / Snapshot

`POST /api/v1/editor/documents/{documentId}/snapshots`

请求使用 `expectedDraftVersion`。事务首先 `FOR UPDATE` 锁住 `editor_document`，因此同文档的并发确认串行进入“按 content hash 复用或创建 revision”的临界区；真实并发门禁证明两个同时确认只形成一个 revision。随后 confirmation/snapshot 固定精确 revision，响应中的 `editorRevisionId` 是导出合同，不是 latest 指针。

## 状态机

```text
legacy
  -> migrating（文档行锁内的事务状态，不持久化）
  -> working_draft
       -> autosave CAS -> working_draft
       -> checkpoint -> working_draft
       -> preview confirmation -> immutable revision + snapshot -> working_draft
       -> rollback materialize -> legacy
```

失败事务不会部分切换 writer mode。`writer_mode` 只有 `legacy` 与 `working_draft` 两个持久状态，避免把短暂执行步骤误当业务生命周期。

## Backfill Runbook

1. 备份并确认 Flyway 当前版本。
2. 部署包含 V008 和 writer-fence 识别逻辑的应用，但先设置 `TEACHBASE_EDITOR_WORKING_DRAFT_ENABLED=false`。
3. 排空所有不理解 `writer_mode` 的更老实例。
4. 停止 editor 写流量，设置标准 PostgreSQL 连接环境变量。
5. 执行全量或指定文档 backfill：

```bash
TEACHBASE_EDITOR_WRITES_DRAINED=true node tools/editor_working_draft_maintenance.mjs backfill
TEACHBASE_EDITOR_WRITES_DRAINED=true node tools/editor_working_draft_maintenance.mjs backfill <document-id> [...]
```

6. 开启新 writer，先小 workspace 验证，再逐步放量。
7. 检查 409、503、mutation replay、checkpoint、revision 增长和 snapshot/export gate。
8. 保留旧表；contract 删除必须是以后单独审批的迁移。

工具按文档独立事务执行，可在中断后重跑。已切换文档返回 `already_working_draft`；不会重复复制。

数据库触发器在 `writer_mode=working_draft` 时拒绝 legacy `editor_draft` 的 INSERT、UPDATE 和 DELETE，专用 SQLSTATE 为 `TB001`。理解新合同的服务使用 503 `editor_writer_fenced`；旧二进制若触发 `TB001`，数据库会回滚整个事务，并应由部署告警捕获该 SQLSTATE。触发器只允许在旧 writer 与回滚窗口全部退役后的独立 contract migration 中显式删除。

## Rollback Runbook

1. 停止 editor 写流量，不要先启动旧应用。
2. 对目标文档运行：

```bash
TEACHBASE_EDITOR_WRITES_DRAINED=true node tools/editor_working_draft_maintenance.mjs rollback-materialize
TEACHBASE_EDITOR_WRITES_DRAINED=true node tools/editor_working_draft_maintenance.mjs rollback-materialize <document-id> [...]
```

3. 验证每个文档 `writer_mode=legacy`，旧 `editor_draft` 指向的 revision hash 等于回滚前 working draft hash。
4. 关闭新 writer，部署旧兼容版本。
5. 不删除 working draft/mutation/checkpoint 表，保留恢复与再次迁移能力。

工具按 content hash 复用 revision；没有可复用内容时创建一条兼容 revision，然后在同一事务中切 mode 和 pointer。重复运行已为 legacy 的文档返回 `already_legacy`。

停止 editor 写流量是 backfill/rollback 的硬前置条件，不是建议。维护命令没有 `TEACHBASE_EDITOR_WRITES_DRAINED=true` 会直接拒绝执行；该变量是编排确认，不会代替实际排流量。文档行锁保证单文档事务、懒迁移和进程重启可恢复，但不能阻止回滚完成后仍存活的新应用再次写入；因此运维顺序必须是排流量、设置确认变量、执行 materialization、验证 hash、切旧 writer。失败或中断时按文档重跑，不会留下半次提交。

## Feature Flags 与观测

| 环境变量 | 默认 | 作用 |
| --- | --- | --- |
| `TEACHBASE_EDITOR_WORKING_DRAFT_ENABLED` | true | 开启新 writer；关闭时写请求 fail closed |
| `TEACHBASE_EDITOR_LAZY_MIGRATION_ENABLED` | true | 首次读取/保存是否允许迁移旧文档 |
| `TEACHBASE_EDITOR_CHECKPOINT_INTERVAL` | 2m | autosave checkpoint 最小间隔 |
| `TEACHBASE_EDITOR_CHECKPOINT_TTL` | 72h | autosave checkpoint TTL |
| `TEACHBASE_EDITOR_CHECKPOINT_MAX` | 100 | 每文档最大 checkpoint 数 |
| `TEACHBASE_EDITOR_MUTATION_TTL` | 7d | autosave 幂等结果保留期 |
| `TEACHBASE_EDITOR_CLEANUP_BATCH_SIZE` | 5000 | 单次幂等记录清理上限 |
| `TEACHBASE_EDITOR_CLEANUP_DELAY` | 5m | 清理任务间隔 |

审计事件 `editor_working_draft.autosaved` 包含 draft version、client mutation ID 与 content hash；精确序列化体积保存在 working draft 的 `content_bytes`。幂等重放不重复记保存事件。HTTP 409/426/503、writer fence 数据库异常和 maintenance JSON 输出可用于灰度告警。

`content_json` 不建立内容索引；大 JSON 由 PostgreSQL TOAST 管理。全量保存仍会产生新 tuple、TOAST/WAL 写入，因此 V008 记录 `content_bytes`，working draft 使用 fillfactor 80，热更新表降低 autovacuum/analyze scale factor。运行环境应监测 `n_tup_upd`、`n_dead_tup`、`last_autovacuum`、主表/TOAST 大小、WAL 增速、保存延迟及 409 比例。

## 测试与报告

核心门禁：

```bash
npm run build:java-foundation
npm run test:wp01-v008-migration
npm run test:wp01-editor-working-draft
npm run test:editor-backend-live
npm run test:question-collection-live
npm run test:document-renderer-live
```

机器报告：

- `docs/reports/wp01_editor_working_draft_gate_20260902.json`
- `docs/reports/wp01_v008_migration_gate_20260902.json`
- `docs/reports/editor_backend_live_gate_20260831.json`
- `docs/reports/question_collection_live_gate_20260831.json`
- `docs/reports/document_renderer_live_gate_20260831.json`

## 未解决事项

- 前端 409 内容合并体验和离线浏览器草稿不属于本工作包。
- `conflict_recovery` 与 `pre_transition` 的产品触发 API 后续按审核流程增加；表与保留合同已冻结。
- 批量 backfill 的生产调度窗口、每批数量和告警阈值需结合首个试用环境确定。
- 旧 `editor_draft` 的 contract/drop 不在 WP-01。
- `BLOCKS_TAG_SCHEMA_AND_SEARCH`（同一 taxonomy 维度最多一个 primary）保持开放；WP-01 没有决定旧主标签降级还是删除。
- 认证、standard module、统一搜索与生产容量仍未关闭。
