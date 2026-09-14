# TAG-FEEDBACK-01A API 合同

Base path：`/api/v1`。所有 ID 均为 UUID，时间为带时区 ISO-8601。示例省略与本合同无关的字段。

## 1. 登记模型运行

```http
POST /api/v1/tagging-runs
```

请求包含 `workspaceId`、`actorUserId`、`externalRunKey`、精确 `taxonomyVersionId`、model/provider/version、`promptProfileVersion`、candidate package key/version/hash、producer/runtime version、`parameters`、`status`、开始/完成时间及可空 G5 request ID。

01A 只登记冻结运行结果，`status` 只允许 `completed` 或 `failed`。

响应：

```json
{
  "taggingRunId": "uuid",
  "replayed": false,
  "runHash": "sha256",
  "parametersHash": "sha256",
  "status": "completed"
}
```

同 external key、同 payload 返回原 ID 且 `replayed=true`；不同 payload 返回 409 `TAG_FEEDBACK_RUN_PAYLOAD_CONFLICT`。

## 2. 登记 SYSTEM_SUGGESTION

```http
POST /api/v1/tagging-runs/{taggingRunId}/question-suggestions
```

```json
{
  "workspaceId": "uuid",
  "actorUserId": "uuid",
  "questionRevisionId": "uuid",
  "taxonomyKey": "senior-math-knowledge",
  "primary": {"taxonomyNodeId": "uuid", "confidence": 0.82, "candidateRank": 9},
  "secondary": [],
  "modelOutputContext": {"resultSchema": "knowledge_tagging_result_v0.2"}
}
```

响应返回 snapshot/state ID、`stateVersion`、status、两个 hash 与 replay 标记。第一次 suggestion 创建 `pending` state；后续模型运行只追加 SYSTEM 历史，不隐式改写已经建立的 current pointer。审核上下文会分别返回最新 SYSTEM suggestion 与显式 current snapshot。

## 3. 读取审核上下文

```http
GET /api/v1/question-revisions/{id}/tag-review-context
  ?workspaceId={uuid}&actorUserId={uuid}&taxonomyKey={key}
```

响应包含精确 question revision、taxonomy version、state version/status、最新 SYSTEM suggestion、current snapshot、对应 run context，以及题目/source provenance 摘要。01A 不提供 taxonomy node picker。

## 4. 提交教师反馈

```http
POST /api/v1/question-revisions/{id}/tag-feedback
```

普通纠偏：

```json
{
  "workspaceId": "uuid",
  "actorUserId": "uuid",
  "taxonomyKey": "senior-math-knowledge",
  "taxonomyVersionId": "uuid",
  "beforeSnapshotId": "uuid",
  "expectedStateVersion": 7,
  "clientMutationId": "stable-client-mutation-id",
  "finalPrimaryNodeId": "uuid",
  "finalSecondaryNodeIds": ["uuid"],
  "reasonCodes": ["PRIMARY_MISSELECTED"],
  "note": "教师说明",
  "taxonomyGap": null
}
```

Taxonomy gap 必须令 `finalPrimaryNodeId=null`，并提供：

```json
{
  "taxonomyGap": {
    "expectedLabelText": "树中缺少的标签名称",
    "explanation": "为什么现有节点不合适"
  }
}
```

成功响应：

```json
{
  "feedbackId": "uuid",
  "replayed": false,
  "stateVersion": 8,
  "tagStatus": "reviewed",
  "currentSnapshotId": "uuid",
  "derivedOperations": [{"code": "PRIMARY_CHANGED"}],
  "taxonomyGapCaseId": null
}
```

同 mutation、同 canonical payload 返回第一次结果并令 `replayed=true`。同 mutation、不同 payload 返回 409 `TAG_FEEDBACK_IDEMPOTENCY_PAYLOAD_CONFLICT`。

过期版本、before snapshot 或 taxonomy version 冲突返回 409，problem body 额外包含 `currentStateVersion`、`currentSnapshotId` 与 `tagStatus`。客户端必须显式刷新/合并，服务端不会静默覆盖。

## 5. 单题历史

```http
GET /api/v1/question-revisions/{id}/tag-feedback-history
  ?workspaceId={uuid}&actorUserId={uuid}&taxonomyKey={key}
```

响应按时间返回完整 SYSTEM/HUMAN snapshots、feedback reason/note/actor/time 和 taxonomy gap。该端点用于教师回看与审计，不是全局分析查询。

## 6. 稳定错误码

| HTTP | 代表错误 |
| --- | --- |
| 400 | `TAG_FEEDBACK_REQUEST_INVALID`、标签重复、primary/gap 不合法、hash/time/context 不合法 |
| 403 | `TAG_FEEDBACK_ACCESS_DENIED` |
| 404 | 当前 workspace 内 run/question/taxonomy/state/snapshot 不存在 |
| 409 | run 或 mutation payload 冲突、state/before snapshot/taxonomy version CAS 冲突 |

权限校验不是生产登录认证。生产 OIDC/session principal 与完整 ACL 仍为开放 Gate。
