# TAG-FEEDBACK-01A 本地验收报告

状态：Feedback Capture Core 已在干净提交上完成本地验收。

## 1. 范围结论

本工作包新增标签运行、系统原判、人工终判、当前状态和 taxonomy gap 的独立持久化边界。标签修改不会创建 `question_revision`，不会调用或修改 Question Review，不会移动 `question.approved_revision_id`，也不会改写 `question_taxonomy_link` 或旧自由文本标签。

G5 v1 的 schema、导入 API 和运行语义保持不变。为允许 V011 存在，`run_g5_v010_migration_gate.mjs` 仅将 V010 门禁的 migration 发现逻辑改为显式截取 V001-V010，不再错误要求目录总数恰好为 10。

## 2. 交付物

- migration：`backend/teachbase-server/src/main/resources/db/migration/V011__teacher_tag_feedback_capture_core.sql`；
- Java module：`backend/teachbase-server/src/main/java/com/teachbase/server/tagfeedback/`；
- taxonomy 精确版本读取端口：`backend/teachbase-server/src/main/java/com/teachbase/server/taxonomy/api/TaxonomySnapshotDirectory.java`；
- 领域合同：`docs/backend/tag-feedback-01a-domain-contract.md`；
- API 合同：`docs/backend/tag-feedback-01a-api-contract.md`；
- 真实模型 fixture：`tests/fixtures/tag_feedback/real_math_case054_model_excerpt.json`；
- migration gate：`tools/run_tag_feedback_v011_migration_gate.mjs`；
- live gate：`tools/run_tag_feedback_01a_live_gate.mjs`；
- 静态合同测试：`tests/test_tag_feedback_01a_contract.py`。

## 3. 数据库验收

PostgreSQL 18.4 实测：

- 空库 V001 -> V011；
- V010 -> V011；
- 已有 G5/V010 fixture -> V011；
- 六张新表存在；
- 既有 question revision、Review、editor、G4、G5 数据不变；
- primary partial unique 生效；
- snapshot/item 禁止更新和删除；
- `item_count`、插入 guard 与 deferred constraint 阻止提交后追加 item 或提交残缺 snapshot。

机器报告：`docs/reports/tag_feedback_v011_migration_gate.json`。该文件由门禁按次生成，并按现有 `.gitignore` 作为 CI/runtime report 管理。

## 4. 业务验收

Live gate 共 20/20 项通过，覆盖：

- tagging run 同 key 同 payload 重放、异 payload 409；
- 一份真实数学打标 trace 的模型、prompt profile、candidate package、外部知识点键、confidence 与 rank 登记；
- `labelSetHash` 对 secondary 顺序不敏感；
- `snapshotHash` 冻结 run、模型上下文、confidence 与 rank；
- 标准纠偏、unchanged confirmation 和确定性 diff；
- taxonomy gap 独立建案且不伪造 primary；
- 同 mutation 并发重试 100 次只产生一份结果；
- 同 mutation 不同 payload 返回 409；
- 两位老师同时使用 `stateVersion=7` 时恰好一成一败；
- CAS 失败不留下 snapshot、feedback 或 gap 孤儿行；
- review context 与单题历史可重新读取；
- `question_tag_state.current_snapshot_id` 是唯一 current authority；
- question revision 数量增加 0；
- Question Review、approved pointer 与 legacy taxonomy link 完全不变；
- 跨 workspace 的已知 ID 与随机 ID 均不泄露实体存在性。

机器报告：`docs/reports/tag_feedback_01a_live_gate.json`。报告不把本机绝对路径作为可复现输入合同。

## 5. 实际命令与结果

| 命令 | Exit code | 结果 |
| --- | ---: | --- |
| `npm run test:tag-feedback-contract` | 0 | 4/4 passed |
| `npm run test:tag-feedback-v011-migration` | 0 | 9/9 passed，PostgreSQL 18.4 |
| `npm run build:java-foundation` | 0 | Maven unit/package 与 Spring Modulith boundary passed |
| `npm run test:tag-feedback-live` | 0 | 20/20 passed，PostgreSQL 18.4 |
| `npm run test:tag-feedback-01a` | 0 | 中文注释 305/305，随后汇总门禁全部 passed |
| `npm run test:g5-import-live` | 0 | 24/24 passed；10/10 注入故障恢复 |
| `npm run test:g4-handout-foundation` | 0 | G4 23/23；WP-01、editor、question/Review、Release Seed、HTML/MathML、DOCX/OMML、PDF 与 artifact cleanup passed |
| `npm run test:g5-canonical-import` | 0 | G5 V010 8/8、final-chain 110 tests、G5 24/24、G4/WP-01/renderer、absolute-path 0、workflow 5/5 全部 passed |

`npm run test:g5-canonical-import` 的第一次执行发现 V010 gate 对 migration 总数的旧假设并已修正；当时 final-chain cleanroom 只因 01A 尚未提交、工作树非 clean 而拒绝。修正后已在干净提交上完整复跑，exit code 0；`FINAL_CHAIN_FOUNDATION_INTEGRATION` 为 PASS，`FINAL_CHAIN_PRODUCTION_READINESS` 仍按既有合同保持 BLOCKED。

## 6. 安全与身份边界

接口验证 active workspace member、允许角色及题目 subject/stage 对应的 teaching scope。`actorUserId` 仍由调用参数传入，因此当前只完成 business actor authorization / scope validation，不能声明 production identity authentication complete。

## 7. 保持开放

`BLOCKS_TAG_SCHEMA_AND_SEARCH` 保持 OPEN。以下能力明确延后到 01B 或更后续：current taxonomy projection、旧 writer fencing、Search 切换、taxonomy picker、全局反馈查询、JSONL export、历史回填、多 primary 治理、inherited candidate、analytics、自动 prompt/训练/taxonomy 修改、gap 发布策略、OIDC 与完整 ACL。

本工作包没有实施统一搜索、推荐、模型策略修改、风险路由修改、G4 composition 修改或四条生产链内部改造。
