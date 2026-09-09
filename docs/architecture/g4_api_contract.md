# G4 Java API 合同

状态：`FROZEN_FOR_G4`

本合同只覆盖标准模块和讲义 composition 基础。它不定义统一 Import Contract、搜索、推荐、风险自动放行或批量 Release Seed。

## 1. 标准模块

### 创建稳定身份和首个 revision

`POST /api/v1/standard-modules`

请求包含 `workspaceId`、`actorUserId`、`moduleKey`、`moduleType`、`title`、`subject`、`stage`、`grade`、`schemaVersion` 和对象型 `content`。

- `moduleKey` 在 workspace 内稳定唯一。
- 内容哈希覆盖标题、学科、学段、年级、schema 和正文。
- 相同 key、type、hash 的重试复用 revision；同 key 不同 type 拒绝。
- 成功新建返回 `201`；幂等复用返回 `200`。

### 追加 revision

`POST /api/v1/standard-modules/{standardModuleId}/revisions`

只追加不可变 revision；相同内容 hash 复用既有 revision。正文不可 UPDATE/DELETE，审核只允许改变 `review_status`、`approved_at` 和根对象的 approved pointer。

### 来源与文件

- `POST /api/v1/standard-modules/revisions/{revisionId}/sources`
- `POST /api/v1/standard-modules/revisions/{revisionId}/files`

来源使用 revision 内唯一 `sourceEvidenceKey`；文件使用 revision 内唯一 `referenceKey`。相同 key 的同 payload 重试幂等，不同 payload fail closed。

### 审核、taxonomy 和 usage

- `POST /api/v1/review-cases/standard-modules`
- `POST /api/v1/review-cases/{reviewCaseId}/decisions`
- `POST /api/v1/taxonomies/standard-module-assignments`
- `GET /api/v1/standard-modules/revisions/{revisionId}/usage?workspaceId=...&actorUserId=...`

Review Case 精确指向 module revision。taxonomy 也指向精确 revision；G4 测试只使用 `secondary`，不提前决定主标签替换规则。

## 2. 讲义 composition

`POST /api/v1/handouts/{editorDocumentId}/revisions/{editorRevisionId}/composition`

请求由 `workspaceId`、`actorUserId`、`editions[]` 和 `artifacts[]` 组成。目标 editor revision 必须已经存在；本接口不创建 editor revision，也不读取或修改 working draft。

每个请求必须恰有一个 `canonical` edition。`projection` edition 必须用 `canonicalTeacherEditionKey` 指向同一请求中的 canonical teacher，并最终在数据库中固定其精确 edition revision ID。

`occurrences[]` 支持四种 kind：

| kind | 内容合同 |
|---|---|
| `container` | 仅组织 parent/order，不承载资产正文 |
| `question` | 精确 `questionRevisionId` |
| `standard_module` | 精确 `standardModuleRevisionId` |
| `ordinary_content` | 对象型 `localContent` |

`occurrenceKey` 在 editor document 内稳定；parent、position、引用目标、local content 和 attributes 属于不可变 edition revision。同一资产 revision 可由多个 occurrence 引用。

`ordinary_content` 只允许承载不需要独立 identity、revision、Review、跨讲义复用、独立搜索或生命周期的局部内容。Question、标准模块、Knowledge Document 或任何需要独立治理的对象不得为了方便塞入 `localContent`。

每个 occurrence 的 `sources[]` 是 placement provenance，不会覆盖题目或模块自身的 canonical provenance。

`artifacts[]` 只允许 `original_docx`、`split_manifest`、`preservation_bundle`、`roundtrip_output`。所有项目必须指向精确 `fileVersionId`；`original_docx` 还必须指向由同一 file version 注册的 `sourceDocumentId`。

## 3. 幂等与错误

- 同一 editor revision、edition 和相同 canonical hash 的并发请求只创建一份 edition revision。
- 重放返回同一 ID，并标记 `replayed=true`。
- 相同 edition/artifact key 携带不同 payload 返回 `400`，不覆盖已提交内容。
- 一个精确 editor revision 的 composition 冻结后不得产生 v2/v3；内容变化必须先创建 editor revision N+1。
- workspace 越界返回 `400 handout_editor_revision_not_found`，不泄露外部对象存在性。
- Bean Validation 错误返回 RFC 9457 `400 request_validation_failed`。

## 4. 版本边界

G4 composition 是精确 editor revision 的结构化投影，不替代 `editor_revision.master_doc_json`，也不改变 WP-01 的 autosave、checkpoint、preview confirmation 或 snapshot 合同。存储 Gate 通过不代表 DOCX/PDF renderer 新能力已经通过。
