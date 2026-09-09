# G5 Canonical Content Import Contract

合同版本：`teachbase.canonical-content-import.v1`

核心术语固定为：`stable identity`、`immutable revision`、`occurrence`、`source evidence`。
它们是四个不同层次，任何 producer 都不得用复制资产或制造空 revision 互相代替。
`teacher` 是 canonical composition，`student` 只能是固定 teacher revision 的 projection/delta。
现有 `Release Seed` 保持兼容入口，不继续膨胀为新的 canonical core。

## 1. Package

```json
{
  "contractVersion": "teachbase.canonical-content-import.v1",
  "importRequest": { "packageKey": "producer-stable-key", "producer": "pipeline-id" },
  "sourceDocuments": [],
  "sourceRegions": [],
  "fileReferences": [],
  "questions": [],
  "standardModules": [],
  "taxonomyAssignments": [],
  "reviewIntents": [],
  "handout": {},
  "lineage": {},
  "producerMetadata": {}
}
```

整个 package 经 JSON key canonicalization 后计算 SHA-256。客户端可声明 `packageHash`，声明值必须与服务端计算值一致。

## 2. 逻辑引用

包内引用只使用稳定逻辑 key：`fileKey`、`sourceDocumentKey`、`sourceRegionKey`、`questionKey`、`moduleKey`、`editorDocumentKey`、`occurrenceKey`。数据库 UUID 只出现在执行结果，不作为调用方规避稳定身份的输入。

Question 和 Standard Module 的正文结构沿用各自领域合同；导入 reviewStatus 只允许 `unreviewed` 或 `pending_review`。Import success 不等于 approved。

## 3. ordinary_content

`ordinary_content` 只承载不需要独立稳定 identity、revision、Review、跨讲义复用、独立搜索或生命周期的局部内容，例如小标题、指令、过渡文字、分页提示和一次性富文本。

Question、可复用标准模块、Knowledge Document 以及任何需要独立治理的内容必须作为正式资产引用。对象一旦需要独立 identity/revision/review/reuse，就必须升级资产类型，不能继续膨胀 `localContent`。

## 4. frozen composition

精确 `editor_revision` 的 canonical composition 一旦提交即冻结：

- 相同 payload 重放复用既有 edition revision；
- 不同 payload fail closed；
- 不允许覆盖或补写 composition v2/v3；
- 内容变化必须创建 editor revision N+1，再提交新 composition。

Student edition 只能是固定 teacher edition revision 的 projection + rules + delta，不拥有第二套 Question/Module。delta 引用的 occurrence key 必须在 canonical teacher composition 中存在。

## 5. API

```text
POST /api/v1/content-imports/validate
POST /api/v1/content-imports/{importRequestId}/commit
GET  /api/v1/content-imports/{importRequestId}
POST /api/v1/content-imports/{importRequestId}/resume
POST /api/v1/content-imports/{importRequestId}/verify
```

Validate 创建或复用 ledger 和 DAG，不写业务 revision。Commit 只接受 validated/failed request 的精确 package hash。Resume 重新验证 completed targets 并继续依赖前沿。Verify 比较稳定 ID、revision ID、hash、evidence、occurrence、composition 和 artifact 指纹，不只比较数量。

所有接口需要 workspace 和 actor；跨 workspace 返回稳定的不可枚举错误。错误使用 RFC 9457，detail 为稳定 error code。

## 6. 状态

Request：`validated -> importing -> failed|completed`。失效 lease 可以从 importing 回收。Completed request 只允许 verify/replay。

Operation：`pending -> running -> completed|failed`。每次执行增加 attempt；completed target identity/hash 不可改写。

## 7. Artifact 与路径

Package 只携带逻辑 artifact key 和已注册 `fileKey`。Java 最终解析到 workspace 内精确 file version。正式合同禁止本机绝对路径。允许角色仅沿用 G4：`original_docx`、`split_manifest`、`preservation_bundle`、`roundtrip_output`。

## 8. Review/Risk

G5 可以创建 pending Review intent，但不做审核决定，不做 LOW 自动放行，不做 HIGH/S02 路由。风险治理属于后续工作包。
