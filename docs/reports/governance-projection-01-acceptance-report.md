# GOVERNANCE-PROJECTION-01 Acceptance Report

## Scope

本工作包实现 Tag/Difficulty 当前治理状态的可重建 PostgreSQL 读取投影。没有修改标签或
难度模型、prompt、Question Revision、G5 v1、历史 migration 或四条生产链。

## Evidence Commands

- `npm run test:governance-projection-contract`
- `npm run test:governance-projection-v013-migration`
- `npm run build:java-foundation`
- `npm run test:governance-projection-live`
- `npm run test:governance-projection-01`

机器报告：

- `docs/reports/governance_projection_v013_migration_gate.json`
- `docs/reports/governance_projection_01_live_gate.json`
- `docs/reports/governance_projection_01_acceptance_evidence.json`

## Boundary Result

- FACT AUTHORITY：未修改。
- CURRENT AUTHORITY：只读 state/current snapshot；trigger 同事务追加 outbox。
- PROJECTION：Tag、secondary、Difficulty 分表，可增量刷新和 full rebuild。
- LEGACY FALLBACK：旧标签文字和 `difficulty_stars` 保持原样，不作为投影 authority。

## Deferred

- `BLOCKS_TAG_SCHEMA_AND_SEARCH` 保持 OPEN。
- unified/fuzzy/semantic search、推荐、统计、模型训练、taxonomy 自动治理不在本轮。
- 生产认证、完整 ACL 与容量压测仍是后续门禁。
