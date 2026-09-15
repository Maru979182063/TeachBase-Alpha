# Governance Projection 01 API and Operations

## Query API

```http
GET /api/v1/questions/governance-query
```

必填参数：`workspaceId`、`actorUserId`。可选精确过滤：

- `subject`、`stage`
- `taxonomyKey`、`primaryTagId`、`secondaryTagId`
- `rubricKey`、`difficultyContextKey`、`difficultyValue`
- `cursor`、`limit`（1–100）

返回每个 `questionRevisionId` 对应的 Tag 与 Difficulty 投影数组。读取者仍需根据自己的
业务规则决定 Review 可见性；本端点不替代既有 approved-question 搜索。

## Rebuild

```http
POST /api/v1/internal/governance-projections/rebuild
Content-Type: application/json

{
  "actorUserId": "<owner-or-admin>",
  "workspaceId": "<optional-workspace>"
}
```

- 指定 workspace 时只重建该 workspace。
- `workspaceId=null` 时重建该 actor 具有 owner/admin 权限的全部 workspace。
- 单个维护请求在一个事务中重建该 actor 获准的 workspace；任一 workspace 失败时整次请求回滚，
  不留下半套投影。生产大规模重建的分片和容量演练仍属于开放门禁。

## Health

```http
GET /api/v1/internal/governance-projections/health?workspaceId=...&actorUserId=...
```

返回 pending/failed event 数、最老待处理事件秒数、最后成功时间，以及 Tag/Difficulty
authority version 落后数量。

## Worker Configuration

```text
TEACHBASE_GOVERNANCE_PROJECTION_ENABLED=true
TEACHBASE_GOVERNANCE_PROJECTION_POLL_DELAY=1s
TEACHBASE_GOVERNANCE_PROJECTION_LEASE_DURATION=30s
TEACHBASE_GOVERNANCE_PROJECTION_RETRY_DELAY=5s
TEACHBASE_GOVERNANCE_PROJECTION_BATCH_SIZE=50
```

生产认证与完整 ACL 尚未关闭；当前 API 延续现有 workspace member 业务授权边界。
