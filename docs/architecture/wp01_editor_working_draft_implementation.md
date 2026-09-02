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
| `editor_autosave_mutation` | 7 天幂等结果，唯一键为 workspace/document/mutation |
| `editor_draft_checkpoint` | 短期完整 JSON 恢复点 |
| legacy writer trigger | working-draft 模式下拒绝旧 `editor_draft` 写入 |

V008 是根据现有组合外键、workspace member、审计与 jOOQ DDL generation 重新编写的 expand migration，不是复制 Phase 0 spike。它不删除、不改写、不回填既有 revision/snapshot/export。

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

### 题目落位

`POST /api/v1/editor/documents/{documentId}/question-references`

同样使用 `expectedDraftVersion` 和 `clientMutationId`。autosave 内容中保存精确 `questionRevisionId`；正式关系索引在 preview confirmation 冻结 revision 时建立，避免把可变草稿伪装成发布引用。

### Preview Confirmation / Snapshot

`POST /api/v1/editor/documents/{documentId}/snapshots`

请求使用 `expectedDraftVersion`。事务锁住文档和 working draft，按 content hash 复用或创建 exactly one revision，再创建引用该精确 revision 的 confirmation/snapshot。响应中的 `editorRevisionId` 是导出合同，不是 latest 指针。

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
node tools/editor_working_draft_maintenance.mjs backfill
node tools/editor_working_draft_maintenance.mjs backfill <document-id> [...]
```

6. 开启新 writer，先小 workspace 验证，再逐步放量。
7. 检查 409、503、mutation replay、checkpoint、revision 增长和 snapshot/export gate。
8. 保留旧表；contract 删除必须是以后单独审批的迁移。

工具按文档独立事务执行，可在中断后重跑。已切换文档返回 `already_working_draft`；不会重复复制。

## Rollback Runbook

1. 停止 editor 写流量，不要先启动旧应用。
2. 对目标文档运行：

```bash
node tools/editor_working_draft_maintenance.mjs rollback-materialize
node tools/editor_working_draft_maintenance.mjs rollback-materialize <document-id> [...]
```

3. 验证每个文档 `writer_mode=legacy`，旧 `editor_draft` 指向的 revision hash 等于回滚前 working draft hash。
4. 关闭新 writer，部署旧兼容版本。
5. 不删除 working draft/mutation/checkpoint 表，保留恢复与再次迁移能力。

工具按 content hash 复用 revision；没有可复用内容时创建一条兼容 revision，然后在同一事务中切 mode 和 pointer。重复运行已为 legacy 的文档返回 `already_legacy`。

## Feature Flags 与观测

| 环境变量 | 默认 | 作用 |
| --- | --- | --- |
| `TEACHBASE_EDITOR_WORKING_DRAFT_ENABLED` | true | 开启新 writer；关闭时写请求 fail closed |
| `TEACHBASE_EDITOR_LAZY_MIGRATION_ENABLED` | true | 首次读取/保存是否允许迁移旧文档 |
| `TEACHBASE_EDITOR_CHECKPOINT_INTERVAL` | 2m | autosave checkpoint 最小间隔 |
| `TEACHBASE_EDITOR_CHECKPOINT_TTL` | 72h | autosave checkpoint TTL |
| `TEACHBASE_EDITOR_CHECKPOINT_MAX` | 100 | 每文档最大 checkpoint 数 |
| `TEACHBASE_EDITOR_MUTATION_TTL` | 7d | autosave 幂等结果保留期 |
| `TEACHBASE_EDITOR_CLEANUP_DELAY` | 1h | 清理任务间隔 |

审计事件 `editor_working_draft.autosaved` 包含 draft version、client mutation ID 与 content hash。幂等重放不重复记保存事件。HTTP 409/503、writer fence 数据库异常和 maintenance JSON 输出可用于灰度告警。

## 测试与报告

核心门禁：

```bash
npm run build:java-foundation
npm run test:wp01-editor-working-draft
npm run test:editor-backend-live
npm run test:question-collection-live
npm run test:document-renderer-live
```

机器报告：

- `docs/reports/wp01_editor_working_draft_gate_20260902.json`
- `docs/reports/editor_backend_live_gate_20260831.json`
- `docs/reports/question_collection_live_gate_20260831.json`
- `docs/reports/document_renderer_live_gate_20260831.json`

## 未解决事项

- 前端 409 内容合并体验和离线浏览器草稿不属于本工作包。
- `conflict_recovery` 与 `pre_transition` 的产品触发 API 后续按审核流程增加；表与保留合同已冻结。
- 批量 backfill 的生产调度窗口、每批数量和告警阈值需结合首个试用环境确定。
- 旧 `editor_draft` 的 contract/drop 不在 WP-01。
- 主知识点唯一 Gate、认证、standard module、统一搜索与生产容量仍未关闭。
