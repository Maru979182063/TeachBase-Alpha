# Production Readiness Audit

更新日期：2026-06-23

## 本轮审计范围

- `tools/runtime_backbone_postgres_store.mjs`
- `tools/runtime_backbone_store.mjs`
- `tools/runtime_backbone_store_interface.mjs`
- `tools/mock_workbench_api_server.mjs`
- `config/migrations/20260623_runtime_backbone_validation.sql`
- `config/migrations/20260623_postgres_sole_source.sql`
- `runtime/postgres/`
- `tests/`

## 审计结论

### 1. ARCH-001 已关闭

Postgres 正式链路已不再把 `runtime_state_snapshot` 当作主状态来源。

当前正式语义：

- 业务读：从归一化表还原状态
- 业务写：从归一化表读取当前事实，执行纯业务变更，再按主键增量落库
- snapshot：仅保留为 debug-only 能力，默认不参与正式业务

### 2. 归一化表覆盖面已补齐到验证版可闭环

本轮新增了验证阶段必需的事实表，使现有 lesson / review / publication / task / component / job / artifact 相关业务逻辑可以脱离 snapshot 独立运行。

### 3. consistency 基准已切换

一致性检查不再要求：

- “表必须永远等于 snapshot”

而是检查：

- 归一化表内部序列化 / 反序列化是否自洽
- 业务表哈希与表还原态是否一致

### 4. 架构门禁已具备真实行为验证

已补充真实行为测试验证：

- 无 snapshot 行也能启动
- 损坏 snapshot 行不会污染 lesson/detail/list/search
- 业务写入不会刷新 debug snapshot
- 同库新实例仍可从业务表恢复事实

## 当前架构形态

### 已完成

- sole-source 验证版
- 表事实读写主链路
- debug snapshot 降级
- 回归门禁补齐

### 尚未作为本轮目标处理

- 最终版全学科终局 ERD
- 热点路径的领域级 SQL 仓储彻底拆分
- 更大体量数据下的专门索引 / 分区 / 长时压测策略

## 结论

从本轮“生产前究极测试与缺陷修复阶段”的唯一主目标来看，`ARCH-001 postgres_snapshot_still_primary_source` 已经实质关闭。  
结合最新 `production readiness` 总回归 `27/27` 通过，当前可判定为：`READY`。
