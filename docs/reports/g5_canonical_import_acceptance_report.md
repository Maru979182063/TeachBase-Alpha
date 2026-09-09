# G5 Canonical Content Import & Recovery 验收报告

## 结论

状态：`G5_CANONICAL_IMPORT_LOCAL_COMPLETE`

G5 建立了 Java Backend 唯一正式内容收货合同 `teachbase.canonical-content-import.v1`。最终测试 SHA、branch 和工作树状态记录在机器证据的 `implementation` 节点；生产解析链适配不因 schema 可承载而被宣称已接通。

## 已实现

- V010 追加 `canonical_import_request`、`canonical_import_operation` 和 editor stable import identity。
- Validate 冻结规范 package、hash 和显式 DAG，不创建正式业务 revision。
- Commit/Resume 逐 operation 使用短事务、request 行锁、worker fencing token 与租约续期。
- Question、Standard Module、source、taxonomy、Review intent、editor revision 和 handout composition 均通过公开模块端口写入。
- Package、asset、revision、evidence、occurrence 五层幂等分别保留，冲突 fail closed。
- Verify 复算 ledger fingerprint，并核对已完成 target 仍存在。
- ordinary_content 与 frozen composition 继续遵守 G4 边界。

## 已实测

- PostgreSQL 空库 V001→V010 和已有 V009→V010。
- 圆讲义：320 source block、31 question occurrence/revision、3 standard module。
- 英语讲义：439 source block、63 question occurrence、60 question revision、3 module、4 container、teacher/student projection。
- 十个 operation 前后故障点均可恢复；恢复后 target ID、revision ID 和 hash 重放不变。
- evidence、occurrence、artifact 永久冲突，坏 projection、跨 workspace 引用均 fail closed。
- 同 package 四路并发只形成一套稳定资产。

## 只设计未实现

- 四条生产解析链到 G5 package 的各自 producer adapter。本轮只冻结统一出口，不修改链路内部。
- G4 composition 到最终 DOCX/PDF 的专用重组导出 adapter。
- 生产容量、线上迁移演练与长期 worker 调度。

## 延后与开放 Gate

- `BLOCKS_TAG_SCHEMA_AND_SEARCH` 保持 OPEN，主标签降级/删除规则未决定。
- Risk 自动放行、S02 自动路由、unified/module search、推荐、AI 生成、Knowledge Document、Question Group、OIDC/完整 ACL 均延后。
- Release Seed 保持 legacy 兼容入口，不扩展旧合同；正式生产内容应使用 G5。

## 证据

- `docs/reports/g5_v010_migration_gate.json`
- `docs/reports/g5_canonical_import_live_gate.json`
- `docs/reports/g5_canonical_import_acceptance_evidence.json`
- `npm run test:g5-canonical-import`

| 验收项 | 结果 |
|---|---:|
| V010 migration | 8/8 |
| G5 live contract/recovery | 24/24 |
| G4 handout foundation | 23/23 |
| WP-01 working draft | 21/21 |
| G5 workflow/schema contract | 4/4 |
| Final Chain Foundation | PASS，内部 107 项 pytest 通过 |
| Java 中文注释 | 288/288 |
| Active absolute path | 0 |

报告和 package 合同均不把本机绝对路径作为可复现输入。
