# Production Readiness Final Report

更新日期：2026-06-23

## 最终结论

当前状态：`READY`

本轮已经关闭 `ARCH-001 postgres_snapshot_still_primary_source`。  
Postgres 模式现在以归一化业务表作为唯一正式事实源，`runtime_state_snapshot` 已降级为调试快照能力，默认不参与正式读写链路。

## 本轮结果

- `npm run test:production-readiness`：`27 / 27` 通过，`0` 失败，`0` 跳过
- 最终状态：`READY`
- 最新报告目录：
  - `outputs/production_readiness/production_readiness_2026-06-23T11-28-45-167Z_a95d6b0f`
- 最新 JSON 报告：
  - `outputs/production_readiness/production_readiness_2026-06-23T11-28-45-167Z_a95d6b0f/production_readiness_report.json`
- 最新 Markdown 摘要：
  - `outputs/production_readiness/production_readiness_2026-06-23T11-28-45-167Z_a95d6b0f/production_readiness_summary.md`

## 已完成的关键架构收口

### 1. Postgres 正式切到表为准

- `tools/runtime_backbone_postgres_store.mjs` 不再从 `runtime_state_snapshot` 读取主状态
- 正式业务查询统一从归一化表还原运行态
- 正式业务写入统一从归一化表读取当前事实、执行纯业务变更、再按主键增量落库
- `POSTGRES_SOLE_SOURCE=true` 成为 Postgres 模式的正式语义

### 2. 补齐了验证阶段所需的事实表

新增迁移：

- `config/migrations/20260623_postgres_sole_source.sql`

新增覆盖的事实域包括：

- runtime metadata
- document source / group / member / relation
- lesson import
- job dependency / outbox event
- component link
- source node / source node revision
- task / task revision
- checkpoint catalog / version / node
- source node checkpoint link
- task checkpoint override
- task subject ext
- quality evaluation

### 3. snapshot 已降级为调试角色

- 正式业务事务默认不再写 debug snapshot
- 即使存在损坏或过期 snapshot，也不会污染 lesson/detail/search/publish 结果
- consistency checker 的基准已改为“归一化表内部一致性”，而不是“表必须永远和 snapshot 完全相同”

### 4. 新增了真实行为门禁

新增或增强测试：

- `tests/audit/runtime_architecture_gate.mjs`
- `tests/postgres-sole-source/runtime_postgres_sole_source.mjs`

已验证：

- 无 snapshot 行也能启动
- 有损坏 snapshot 行也能正常 import / approve / publish
- 同库二次启动仍能从归一化表读回真实 lesson
- 业务写入不会刷新 debug snapshot

## 关键测试结论

核心套件全部通过：

- audit
- postgres-sole-source
- static
- migrations
- store-contract
- api
- business
- concurrency
- failure-injection
- security
- performance
- backup-restore

重点结论：

- `ARCH-001`：已通过
- `S0 = 0`
- `S1 = 0`
- 备份恢复 `N01-N04`：已通过
- smoke 性能仍在阈值内

## 当前残余风险

以下项已不再阻塞当前 `READY` 结论，但仍建议作为下一阶段优化：

1. 当前验证版仓储仍会在写事务里还原整份表状态，再执行纯函数变更；这已经不再依赖 snapshot，但长期仍建议继续拆分热点领域仓储。
2. 当前还不是最终目标版 ERD；本轮是“Postgres sole source 验证版”，不是终局数据建模版。
3. 如果后续要承接更高并发或更大题库体量，建议继续推进：
   - lesson / review / publication 专项仓储
   - task / artifact / lineage 专项查询
   - 更长时间的 soak 与更高强度压测

## 相关文档

- 迁移说明：`docs/postgres_sole_source_migration_plan.md`
- 测试总报告：`docs/production_readiness_final_report.md`
- 缺陷状态：`docs/production_readiness_defects.md`
