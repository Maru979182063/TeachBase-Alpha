# Production Readiness Defects

更新日期：2026-06-23

## 已关闭阻断项

### S1-ARCH-001 Postgres 仍以 snapshot 作为主事实源

- 状态：`已关闭`
- 原问题：
  - `PostgresRuntimeBackboneStore` 先读取 `runtime_state_snapshot`
  - 再在内存中执行整份 state 变更
  - 最后覆盖 mirror tables
- 风险：
  - Postgres 与 snapshot 形成双事实源
  - 正式业务查询会被过期或损坏 snapshot 污染
  - 架构门禁 `ARCH-001` 无法通过
- 本轮修复：
  - 正式读链路切为归一化表还原
  - 正式写链路切为表事实读取 + 主键级增量 upsert/delete
  - `runtime_state_snapshot` 降级为 debug-only，默认不参与业务
  - consistency checker 改为以归一化表为基准
- 相关文件：
  - `tools/runtime_backbone_postgres_store.mjs`
  - `runtime/postgres/state_repository.mjs`
  - `runtime/postgres/state_table_configs.mjs`
  - `runtime/postgres/snapshot_repository.mjs`
  - `config/migrations/20260623_postgres_sole_source.sql`
- 回归覆盖：
  - `ARCH-001`
  - `PGSS-01`
  - `PGSS-02`
  - `API-E2E`
  - `D12-E10`

### S0-BACKUP-001 备份恢复基础链路缺少本机工具

- 状态：`已关闭`
- 说明：
  - `pg_dump` / `pg_restore` 环境已补齐
  - `N01-N04` 备份恢复链路已通过

## 当前阻断状态

- `S0 = 0`
- `S1 = 0`

当前没有阻塞 `READY` 结论的未关闭缺陷。

## 后续优化项

以下为后续架构优化，不再归类为当前阻断缺陷：

### V2-001 验证版仓储仍有整态还原成本

- 当前状态：`待优化`
- 说明：
  - 正式链路已不再依赖 snapshot
  - 但验证版写事务仍会先从归一化表还原当前状态，再复用纯函数做业务变更
- 建议：
  - 将 lesson / review / publication / artifact 等热点路径继续拆为领域仓储

### V2-002 终局版 ERD 仍未完成

- 当前状态：`待优化`
- 说明：
  - 本轮完成的是 sole-source 验证版，不是最终目标版全量 ERD
- 建议：
  - 后续再做最终领域边界、索引策略和热点查询模型收口

### V2-003 长时压测与扩容验证可继续增强

- 当前状态：`待优化`
- 已有结果：
  - smoke load 已通过
  - 备份恢复已通过
- 建议：
  - 增加更长时间 soak
  - 增加更高并发压测
  - 在更接近真实题库体量的数据集上复测
