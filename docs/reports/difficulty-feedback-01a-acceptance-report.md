# DIFFICULTY-FEEDBACK-01A 本地验收报告

状态：本报告随实现提交；最终状态要求下列命令在该干净提交上全部通过。

## 交付

- V012 纯追加 migration；
- 独立 `difficultyfeedback` Java Modulith module；
- rubric/run/system suggestion/feedback/context/history API；
- 版本化 1–5 rubric 与人群 context；
- immutable snapshot、current pointer、CAS、mutation idempotency 与 rubric gap；
- machine-readable migration/live reports。

## 已验证项目

- 空库 V001 -> V012 与 V011 -> V012；
- V011 question revision、Review 和 TAG-FEEDBACK-01A 数据保持不变；
- rubric/snapshot immutable 和 1–5 DB check；
- rubric/run replay 与异 payload 冲突；
- failed run 不得产生 suggestion；
- 同 context key 异 context payload 冲突；
- 纠偏、unchanged confirmation、rubric gap；
- 100 次相同 mutation 只产生一个结果；
- 两个老师同 state version 恰好一成一败，失败事务无孤儿；
- review context、单题 history 与跨 workspace non-disclosure；
- question revision 增量为 0；
- Question Review、approved pointer 与旧 `difficulty_stars` 不变。

## 验证命令

| 命令 | Exit code | 结果 |
| --- | ---: | --- |
| `npm run test:difficulty-feedback-contract` | 0 | 3/3 passed |
| `npm run test:difficulty-feedback-v012-migration` | 0 | 7/7 passed，PostgreSQL 18.4 |
| `npm run build:java-foundation` | 0 | Java unit/package 与 Spring Modulith boundary passed |
| `npm run test:difficulty-feedback-live` | 0 | 19/19 passed，PostgreSQL 18.4 |
| `npm run test:difficulty-feedback-01a` | 0 | 中文注释 318/318，汇总门禁 passed |
| `npm run test:tag-feedback-01a` | 0 | TAG-FEEDBACK-01A 20/20 与 V011 9/9 保持 passed |
| `npm run test:g5-canonical-import` | 0 | G5/G4/WP-01/final-chain/renderer aggregate gate passed |

机器报告：

- `docs/reports/difficulty_feedback_v012_migration_gate.json`；
- `docs/reports/difficulty_feedback_01a_live_gate.json`。

上述 JSON 是按次生成的 CI/runtime report，遵循仓库现有 `.gitignore`，不作为长期生成物提交。

当前仓库没有可诚实登记为正式基线的历史难度模型产物，因此 live gate 使用受控模型结果 fixture，不伪造模型或 prompt 版本。正式粗打程序只需按 Assessment Run 与 SYSTEM_SUGGESTION API 登记即可，无需修改 G5 v1。

## 开放边界

搜索仍读取 `question_revision.difficulty_stars`；current difficulty search projection、历史回填、全局分析、rubric 管理后台和生产 OIDC/ACL 均未在本轮实现。
