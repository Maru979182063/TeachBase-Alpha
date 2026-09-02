# ADR-01 Working Draft / Revision / Snapshot

- 状态：Accepted for Phase 0
- 日期：2026-09-02
- 范围：现有 `editor_document` 的编辑、恢复、预览和导出合同

## 背景

当前 `editor_draft` 只是最新 `editor_revision` 的指针；每次 PUT 都插入永久 revision。它通过行锁和 expected revision 避免静默覆盖，但不适合高频自动保存。正式 revision、恢复点和导出快照也因此在概念上混在一起。

## 决定

### 四类对象

| 对象 | 可变 | 用途 | 保留 |
| --- | --- | --- | --- |
| working draft | 是 | 当前编辑真相、自动保存 | 文档存续期间 |
| checkpoint | 否 | 短期恢复和冲突救援 | 按类型清理 |
| editor revision | 否 | 正式版本点、审核或发布依据 | 永久 |
| snapshot | 否 | 已确认的某 variant/audience 交付内容 | 永久或按交付政策 |

### Working draft

- 每个 `editor_document` 最多一个 working draft。
- 保存命令必须携带 `expectedDraftVersion`；成功后原子递增 `draftVersion`。
- draft 保存 master document、三个 override、schema version、content hash 和 `basedOnEditorRevisionId`。
- API 返回 ETag `draft-{draftVersion}`。版本不匹配返回 HTTP 409、当前 version 和当前 content hash，不自动覆盖。
- 新文档可以先只有 working draft；兼容阶段允许沿用已有 revision 作为 `basedOnEditorRevisionId`。
- 自动保存仅更新 working draft，不创建 `editor_revision`。

### 自动保存与 checkpoint

- 前端脏数据 debounce 2 秒；持续输入时最多每 15 秒发送一次 autosave。
- 服务端每次 autosave 都更新 working draft；同一文档每 2 分钟最多生成一个 `autosave` checkpoint。
- `autosave` checkpoint 保留 72 小时，且每文档最多保留最近 100 个。
- 发生 409 时，客户端尚未合并的内容可写入 `conflict_recovery` checkpoint，保留 7 天。
- 提交审核、建立手动版本点或预览确认前建立 `pre_transition` checkpoint，保留 30 天。
- 清理 checkpoint 是独立幂等任务；永远不能删除 working draft、revision 或 snapshot。

### 创建 immutable revision 的事件

只允许以下事件创建 `editor_revision`：

1. 用户执行“保存版本”；
2. 提交审核；
3. 发布或激活；
4. preview confirmation 时 working draft 尚未对应精确 revision；
5. 受控导入明确要求建立版本；
6. 从历史 revision 恢复后，用户显式保存版本。

内容 hash 与当前正式 revision 相同且元数据合同未变化时，不创建重复 revision。

### Preview confirmation 与 snapshot

- preview confirmation 必须引用精确 `editor_revision_id`、variant key 和 audience。
- 若用户从未将当前 draft 建成 revision，确认操作在同一事务中先冻结一个 revision，再创建 confirmation。
- snapshot 保存投影后的完整内容、source revision、variant key、audience、schema version 和 hash。
- 导出只读取 snapshot，不读取 working draft、latest 或 approved pointer。
- 已存在 snapshot 永不因后续 draft/revision 修改而变化。

## 兼容迁移

1. 追加 working draft/checkpoint 新表，不删除现有表。
2. 对每个现有 `editor_draft`，读取其指向的 `editor_revision`，复制内容到新 working draft；`draft_version=1`，`based_on_editor_revision_id` 指向原 revision。
3. 迁移期间旧 revision 仍是历史真相。双读只用于发布窗口：优先新 working draft，不存在时读取旧 pointer 并懒迁移。
4. 新写入启用后停止移动旧 `editor_draft` 指针；至少一个发布周期后再决定是否只读保留。
5. 不重写、不合并、不删除既有 `editor_revision` 和 snapshot。

## 并发与恢复

```text
UPDATE working_draft
SET draft_version = draft_version + 1, ...
WHERE editor_document_id = :id
  AND workspace_id = :workspace
  AND draft_version = :expected
```

- affected rows 为 0 即冲突，不做 last-write-wins。
- 同一 expected version 的两个并发保存只能一个成功。
- revision 冻结事务先锁 working draft，再比较 expected draft version 和 content hash。
- checkpoint 恢复只生成新的 working draft version，不修改历史 revision。
- 服务器崩溃后以已提交 working draft 为准；客户端未提交内容由客户端草稿或 conflict checkpoint 恢复。

## 验收测试

- 100 次 autosave 后 `editor_revision` 数量不变，draft version 增加 100。
- 两个并发 expected version 保存恰好一个成功，另一个 409。
- 2 分钟 checkpoint 节流、72 小时/100 个清理上限正确。
- 从 checkpoint 恢复产生新 draft version，原 checkpoint 不变。
- preview confirmation 固定精确 revision；后续 autosave 不改变 snapshot hash。
- 旧 `editor_draft` 可懒迁移，旧 snapshot 仍可导出。

## 不采用的方案

- 不再接受“每次 autosave 都创建永久 revision”。
- 不用 snapshot 充当恢复点。
- 不在 Phase 0 删除旧 editor 表或批量压缩旧 revision。
