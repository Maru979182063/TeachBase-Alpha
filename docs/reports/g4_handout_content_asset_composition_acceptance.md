# G4 Handout Content Asset & Composition Foundation 验收报告

## 1. 结论

状态：`G4_FOUNDATION_LOCAL_COMPLETE`

G4 已在 `integration/repository-scope-clean-20260715@61fd6438d944484bf6d07bb0fed5ed71e055f8ab` 的独立 worktree/分支上完成。实现提交为 `ffb8b2e43f734f7ca2fb5be983213bbc4cabbd54`，完整 gate 在该精确提交上 exit 0。

本轮形成所有学科共用的内容资产层，不是英语特判。未批量灌入讲义，未扩展 Release Seed/Import Contract 对外格式，未修改四条生产链。

## 2. 已完成能力

1. `standard_module` 成为与 `question` 同级的一等资产，拥有稳定 identity、不可变 revision、content hash、Review approved pointer、taxonomy、source region、file version 和 usage back-reference。
2. `question_source_link` 从一 revision 一来源改为 `(question_revision_id, source_evidence_key)` 幂等范围，可保留多条 canonical provenance。
3. canonical provenance 与 handout occurrence placement provenance 分表保存，互不覆盖。
4. `handout_edition`、immutable edition revision、stable occurrence identity、ordered occurrence 和 occurrence source evidence 组成统一 composition。
5. `question`、`standard_module`、`ordinary_content` 与纯 container 可进入同一父子有序树；同一资产 revision 可重复出现。
6. 教师版是 canonical；学生版固定精确 teacher edition revision，并只保存 projection rules/delta，不复制题库。
7. editor revision 强引用原 DOCX、拆分 manifest、preservation bundle 和 roundtrip output 的精确 file version；原 DOCX 同时强校验 source document/file version 一致。
8. PostgreSQL trigger 拒绝 module revision 正文、composition、来源和 artifact 的原地改写。
9. Java `standardmodule` 与 `handout` 模块通过公开 `::api` 依赖现有 editor/question/review/taxonomy/file/source 底座，Spring Modulith 构建测试通过。

## 3. Migration

迁移：[V009__handout_content_asset_and_composition.sql](../../backend/teachbase-server/src/main/resources/db/migration/V009__handout_content_asset_and_composition.sql)

- 空库 V001→V009：通过。
- 既有 V008→V009：通过。
- 旧 question source evidence：完成 legacy key backfill。
- 既有 question revision、editor revision、WP-01 working draft、snapshot：ID/hash/内容不变。
- V009 为前向迁移；数据库迁到 V009 后，不应回退到只理解旧来源唯一键的 writer。

## 4. Golden 验收

### 《时态语态秘密武器》

- 439 个 source block 恰好覆盖一次。
- 63 个 question occurrence 复用 60 个 question revision；3 组人工确认等价题不制造重复资产。
- 3 个 standard module 与 4 个 question container 类型分离。
- 1 个 student projection 固定 teacher revision，新增 student question asset 数为 0。
- 4 个表格 source region、9 个图片 file reference 可持久化和追溯。

### 圆讲义

- 320 个 source block 恰好覆盖一次。
- 31 个 question occurrence 对应 31 个 question revision。
- 3 个 standard module 完成 Review、taxonomy 和来源绑定。

两份 fixture 均由显式 `--source` 输入生成；重新生成的 SHA-256 与仓库 fixture 完全一致。fixture 和报告不把本机绝对路径作为可复现输入合同。

## 5. 并发与隔离

- 同一 composition 4 路并发提交：4 个请求成功返回，但只有一个 creator，其余复用相同 revision。
- 同 edition key 不同 payload：fail closed，不覆盖。
- 同 artifact key 不同 payload：fail closed，不覆盖。
- 跨 workspace 引用 editor revision：拒绝且不泄露目标内容。
- module revision 正文和 occurrence 的直接 SQL UPDATE：PostgreSQL `P0001` 拒绝。
- WP-01 100 次 autosave：新增 immutable editor revision 数为 0；原 21 项 WP-01 gate 全部通过。

## 6. 测试证据

| 命令 | Exit | 结果 |
|---|---:|---|
| `npm run test:g4-handout-foundation` | 0 | 完整组合 gate 通过 |
| `npm run test:g4-v009-migration` | 0 | 6/6 |
| `npm run test:g4-handout-live` | 0 | 23/23 |
| `npm run test:wp01-editor-working-draft` | 0 | 21/21，固定 V008 历史边界 |
| `npm run test:release-seed-loader-live` | 0 | validate/dry-run/import/verify/recovery/idempotency 全通过 |
| `npm run test:active-absolute-paths` | 0 | active absolute path = 0 |
| workflow YAML parse | 0 | 全部 workflow 可解析 |
| Golden fixture regenerate + hash compare | 0 | 英语/圆 fixture 均一致 |

完整 gate 还验证：中文注释 255/255、Java/Modulith build、editor backend、question governance、HTML/MathML、DOCX Native/OMML、PDF parse、worker lease recovery、atomic output 和 temporary residue = 0。

机器报告：[g4_acceptance_evidence.json](g4_acceptance_evidence.json)、[g4_v009_migration_gate.json](g4_v009_migration_gate.json)、[g4_handout_foundation_live_gate.json](g4_handout_foundation_live_gate.json)。

## 7. 富内容边界

G4 已完成数据库存储与强引用 Gate：表格结构、图片 file version、公式/ordinary editor JSON 可以按 revision 保存。现有通用 renderer 回归也通过。

但“从 G4 composition 读取并重组整份真实讲义，再生成 DOCX/PDF”仍是后续导出适配工作，不在本轮伪装成已完成。数据库能承载与特定导出适配器已接通是两个状态。

## 8. 保持开放与明确未做

- `BLOCKS_TAG_SCHEMA_AND_SEARCH`：OPEN；未决定旧主标签降级还是删除。
- 统一 Import Contract、批量 Release Seed、风险自动放行：未启动。
- standard module/unified search、推荐、AI 生成：未启动。
- knowledge document、question group 正式实现：未启动。
- OIDC、四条生产链内部改造：未启动。
- G4 composition 到最终 DOCX/PDF 的专用读取/导出 adapter：未启动。
- 生产容量与线上迁移演练：仍需后续发布 Gate。
