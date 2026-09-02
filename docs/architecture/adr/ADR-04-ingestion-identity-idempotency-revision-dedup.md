# ADR-04 Ingestion Identity / Idempotency / Revision Dedup

- 状态：Accepted for Phase 0
- 日期：2026-09-02
- 范围：四条生产链 artifact manifest 进入 Java 规范域的身份与状态合同

## 核心决定：三个问题使用三个键

### 1. Import retry idempotency

回答“同一次交货重试是否仍是同一个 batch”。

- 客户端生成 `importRequestId`，同一次提交和网络重试必须复用。
- Java 唯一约束：`workspace_id + import_request_id`。
- manifest canonical hash 用于防止同一个 request ID 携带不同内容；若 hash 不同返回 conflict。
- 相同 manifest 由用户主动再次导入但 request ID 不同，可以建立新 batch；item 层 identity/dedup 决定是否产生新业务内容。
- pipeline run ID、profile version 和 package hash 是 batch provenance，不代替 request ID。

### 2. Stable question identity matching

回答“本次 item 对应哪一个稳定 question”。按以下优先级：

1. 已登记来源系统的稳定外部键：`workspace + source_system + external_question_key`。
2. 受控来源锚点：`workspace + source_document_id + locator_contract_version + stable_source_locator`，仅当对应 adapter 声明 locator 在重复转录中稳定。
3. 没有可靠 identity 时创建新 question；semantic similarity/content hash 只能产生 duplicate candidate，禁止自动合并不同题。

`pipeline_profile_version` 不属于 question identity。换模型、prompt 或 profile 后，同一道题仍应命中相同稳定 question。

### 3. Content revision deduplication

回答“命中 question 后是否需要新 revision”。

- 规范化题目业务内容计算 `canonicalContentHash`；包括材料、题干、选项、答案、解析、结构化媒体引用及 content schema version。
- 唯一语义：`question_id + content_schema_version + canonical_content_hash`。
- hash 相同：不创建 revision，只追加 import observation/provenance，记录本次 profile、source、时间和风险结果。
- hash 不同：创建 next immutable question revision。
- source locator、profile version、external key 变化本身不创建内容 revision；它们属于 identity/provenance。

因此禁止把 source locator、profile version、semantic hash 和 external key 拼成一个“万能幂等键”。它会把重试、身份和内容变化混成同一件事。

## Artifact manifest

每条链保留现有内部机制，只在出口生成统一 envelope：

```json
{
  "manifestSchemaVersion": 1,
  "importRequestId": "018f...",
  "workspaceKey": "teaching-main",
  "sourceSystem": "pdf_math",
  "pipelineRunId": "run-20260902-001",
  "pipelineProfileVersion": "pdf-math-final-v3",
  "sourceDocuments": [
    {"sourceDocumentKey": "doc-1", "fileSha256": "...", "mediaType": "application/pdf"}
  ],
  "questions": [
    {
      "itemKey": "q-0001",
      "externalQuestionKey": null,
      "sourceDocumentKey": "doc-1",
      "sourceLocator": {"page": 12, "regionKey": "question-4"},
      "locatorContractVersion": 1,
      "canonicalContentHash": "...",
      "content": {},
      "risk": {"level": "low", "policyVersion": "question-risk-v1", "evidence": {}}
    }
  ]
}
```

- 文件路径必须是 package 内相对路径；Java 校验 sha256 后注册 file/source。
- Java 创建 durable ingestion batch 和 item checkpoint，再通过领域公开端口写 file/source/question/review/taxonomy/audit。
- Python/Node 不直写 canonical 业务表。
- per-item 错误结构化并区分 retryable/final；重启从未完成 item 继续。

## 风险状态转换

```text
artifact accepted
  -> identity matched/created
  -> revision deduplicated/created
  -> append-only risk decision
       low     -> auditable auto-approval -> approved revision pointer
       high    -> pending_review -> S02 case
       unknown -> pending_review -> S02 case (reason = risk_unknown)
```

- 低危不是“绕过记录”，而是写入 `decision_source=risk_auto`、policy version、evidence hash、occurred_at 和 actor/service identity。
- 高危与未知不能由 manifest 直接自报后成为可信结论；Java 只接受已登记 risk evaluator/profile 的签名或在 Java 侧运行确定性校验。
- auto-approval 和 review approval 都必须以 expected content hash 为前置，避免审核/判定后内容被换掉。
- 同一 revision 的相同 policy decision 重放幂等；policy version 变化可追加新 assessment，但不会静默撤销既有生产 revision，撤销另走治理事件。

## 题组导入

- manifest 可以用 `groupItemKey` 声明本包内父材料和子题组合。
- 先完成每个 question identity/revision，再创建精确 composition revision。
- group import retry 使用 batch/item checkpoint；group identity 使用 external group key 或受控 source anchor；composition dedup 使用 composition hash，三者仍然分离。

## 迁移与回滚

- 复用现有 Release Seed 的 package 校验、租约和领域端口模式，不复用其“全部 humanApproved”业务假设。
- 第一阶段增加新 ingestion contract/version，不修改四链节点、prompt、route、threshold 或模型。
- 回滚时停止消费者并保留 artifact package/batch checkpoint；已提交 canonical revision 不删除，失败 batch 可修复后续跑。
- 旧 Release Seed 入口继续存在，直到新入口完成四链各一包的双轨核验。

## 验收测试

- 同 request ID + 同 manifest 重试返回同 batch；同 request ID + 不同 hash 返回 conflict。
- 不同 request ID 的同 item 命中同 question，内容 hash 相同不生 revision。
- profile version 改变但内容相同，只增加 observation。
- external key 相同但内容改变，命中同 question 并创建 next revision。
- 仅语义相似、无稳定 identity 的题不会自动合并。
- low 产生可审计 auto decision 和 approved pointer；high/unknown 产生 S02 case。
- worker 在任意 item 后崩溃可恢复，已完成 item 不重复写。

## Phase 0 未解决但不阻塞合同

- risk policy v1 的具体字段、阈值和签名方式属于后续工作包，不在本轮改变模型策略。
- manifest 的大文件传输协议可在 HTTP multipart 与 object-storage inbox 间择一，不影响三类 key。
