# 真实链路收口结果

更新日期：2026-07-06

这份文档只描述三层事实：

1. 这轮设计目标是什么。
2. 当前仓库代码实际上已经实现了什么。
3. 这次真实跑了什么、产出了什么、还剩什么风险。

不把设计图当成已完成代码，也不把计划当成已跑通结果。

## 1. 总结论

- 当前结论：`GO_FOR_VALIDATION`
- 当前生产结论：`NOT_READY_FOR_PRODUCTION`
- 当前后端定位：`validation baseline`
- 当前真实 staging 结果：
  `outputs/staging_validation/staging_validation_2026-07-06T06-44-50-675Z_f551bfff/staging_report.json`
- 当前最新 Release Gate：
  `outputs/test_runs/release_gate/release_gate_2026-07-06T06-45-41-072Z_facea6b2/report.json`
- 当前最新 production readiness：
  `outputs/production_readiness/production_readiness_2026-07-06T06-51-32-596Z_c7c440ff/production_readiness_report.json`

本轮没有改 DDL，没有扩表，没有把 `NOT_READY` 改成 `READY`。

## 2. 当前代码真实状态

### 2.1 设计上应该是什么

- 视觉拆题和 English runtime manifest 都应该进入现有后端主链路。
- 后端事实源应保持在 Postgres 归一化表，而不是 `runtime_state_snapshot`。
- `validation_baseline` 分支不应自报 production ready。
- export 必须基于真实文件产出，而不是有 artifact 但 `fileCount=0` 的假成功。

### 2.2 当前代码实际上是什么

- `8790` 仍是正式 Runtime API 入口。
- `8792` 仍存在，但只是 deprecated 兼容转发层。
- `tools/runtime_manifest_to_lesson_bundle_adapter.mjs` 已经存在，并且已接入正式导入路径。
- `/api/runtime/imports/runtime-manifest` 已经是正式入口，不再依赖 probe-time conversion。
- visual manifest 仍通过 `LessonDraftBundle` / `source_refs_json.question_visual_structure` 进入后端。
- export 仍使用 `tools/mock_workbench_export_bundle.py` 这条 legacy renderer，但 API 层已经做了枚举标准化与零文件硬失败。
- `runtime_state_snapshot` 仍在 schema 内，但当前主业务写路径已经不把它当成事实源。

### 2.3 这次真实跑了什么

- Step 1 visual export-clean probe：
  `outputs/runtime_real_output_probe/step1_visual_export_clean_validation_2026-07-06T05-20-35-246Z_23161458/step1_visual_export_clean_report.json`
- English adapter 实库验证：
  `outputs/runtime_real_output_probe/english_adapter_validation_2026-07-06T05-56-44-419Z_1b98bb86/english_adapter_validation_report.json`
- long-lived local staging：
  `outputs/staging_validation/staging_validation_2026-07-06T06-44-50-675Z_f551bfff/staging_report.json`
- Release Gate fast rerun：
  `outputs/test_runs/release_gate/release_gate_2026-07-06T06-45-41-072Z_facea6b2/report.json`
- production readiness rerun：
  `outputs/production_readiness/production_readiness_2026-07-06T06-51-32-596Z_c7c440ff/production_readiness_report.json`

## 3. Step 1 visual export-clean 结果

### 已修复

- `evidence_only` 不再被误判为正式导出资产。
- 正式展示资产必须满足：
  - `attach_status=attached`
  - `file_status=materialized`
  - `storage_key` 可解析
  - 有 `source_image_asset_id` 或 `source_image_storage_key`
- 当正式展示资产 `materialize failed` 时，现在会 hard fail。
- evidence source 可以为 formal asset 回填 source refs。

### 真实结果

- `case007_junior_visual`
  - Step 1 probe 中已从 `invalid_export_preflight` 收口到 `export_generated_no_files`
  - 在本轮 staging 中已经进一步通过 preflight，并成功导出真实 DOCX
- `long_anchor_junior_visual`
  - 当前没有进入本轮 staging
  - Step 1 probe 中仍存在正式 analysis asset 的 `formal_asset_not_materialized` 问题
  - 这批并未在本轮被宣称为 export-clean

### 真实文件

- case007 staging DOCX：
  `outputs/split_builder/mock_workbench/export_runs/2026-07-06T06-44-57-759Z_staging_case007_visual/junior数学_g7_summer_Case007_Visual_Validation_基础版_教师版.docx`

## 4. Step 2 导出真实文件结果

### 枚举标准化位置

- `tools/mock_workbench_api_server.mjs`

当前已统一：

- `base` -> `基础版`
- `student` -> `基础版`
- `teacher` -> `教师版`
- `instructor` -> `教师版`
- `answer` -> 明确报错，不再假成功

### 真实结果

- `fileCount=0` 现在返回：
  `export_generated_no_files`
- unsupported version alias 现在返回：
  `unsupported_export_version:answer`
- export 成功时：
  - 文件真实存在
  - size > 0
  - manifest 中记录真实文件

### 本轮实际文件

- visual case007：
  `outputs/split_builder/mock_workbench/export_runs/2026-07-06T06-44-57-759Z_staging_case007_visual/junior数学_g7_summer_Case007_Visual_Validation_基础版_教师版.docx`
- English runtime manifest：
  `outputs/split_builder/mock_workbench/export_runs/2026-07-06T06-45-02-564Z_staging_english_runtime_manifest/senior英语_g11_summer_English_Runtime_Manifest_Validation_基础版_教师版.docx`

### 额外确认

- 英语导出文件名不再硬编码成“数学”。
- qvs visual export 在 staging 中真实生成文件，不再只停留在 preflight 通过。

## 5. Step 3 English adapter 结果

### 当前代码入口

- Adapter 文件：
  `tools/runtime_manifest_to_lesson_bundle_adapter.mjs`
- 入口：
  `POST /api/runtime/imports/runtime-manifest`
- Store 接入点：
  `tools/runtime_backbone_store.mjs`

### 当前代码真实能力

- adapter 只做转换，不直接写 DB
- 转换后仍走现有 import / review / publish 主链路
- 幂等基于 bundle hash / 内容一致性路径生效
- `question_visual_structure`、`source_refs_json.runtime_manifest` 等信息会保留

### 真实运行结果

- 实库验证样例：
  `outputs/runtime_real_output_probe/english_adapter_validation_2026-07-06T05-56-44-419Z_1b98bb86/english_adapter_validation_report.json`
- 本轮 staging：
  - 导入题数：39
  - question bank 创建：8
  - material item：8
  - export 文件：1 个真实 DOCX

### 当前结论

- English runtime manifest 已经不是 probe-time conversion。
- 它现在是正式 backend adapter 路径。

## 6. Step 4 staging DB 结果

### 真实数据库

- masked DB：
  `postgresql://postgres:***@127.0.0.1:55432/teachbase_validation_staging`
- cluster data dir：
  `outputs/staging_validation/local_pg_cluster`
- 实际使用的 initdb / pg_ctl 安装：
  `C:\Program Files\PostgreSQL\17`
- 原因：
  本机 PostgreSQL 18 命令行工具缺少 `share/postgres.bki`，不能用于 `initdb`；脚本已自动回退到本地可用的 17 安装。

### 实际表结构

- public tables：43
- `runtime_state_snapshot` 行数：
  - after migrate：0
  - before backup：0
  - final：0

### 真实业务 ID

- visual lesson：
  - review task：`review_task_8944bb7d2d8a`
  - publication：`publication_dee16fa95115`
  - material build：`material_build_0baede78382d`
  - export artifact：`artifact_a42cecf1f3b2`
- English lesson：
  - review task：`review_task_1129c0ecaacf`
  - publication：`publication_436a90479a68`
  - material build：`material_build_a50b2d00e249`
  - export artifact：`artifact_cf4bbcf56d7c`

### 备份恢复

- backup file：
  `outputs/staging_validation/staging_validation_2026-07-06T06-44-50-675Z_f551bfff/backups/2026-07-06T06-45-03-951Z.dump`
- before / after 计数一致：
  - lesson：5
  - lesson_revision：7
  - task_projection：132
  - question_bank_item：9
  - material_build：2
  - runtime_state_snapshot：0

### 重启复查

- runtime server 已重启后复查
- visual projection：1
- English projection：39
- English question bank：8
- publication / material_build / lesson detail 可重新读出
- 本轮结束时后台进程状态：
  - runtime server：未留存
  - local staging Postgres：未留存

## 7. Step 5 gates

### Release Gate

- 报告：
  `outputs/test_runs/release_gate/release_gate_2026-07-06T06-45-41-072Z_facea6b2/report.json`
- 命令：
  `node tests/release_gate/run_release_gate.mjs --fast --skip-performance --report-json --report-md`
- 结果：
  - total：57
  - passed：57
  - failed：0
  - verdict：`GO WITH WARNINGS`
- warning 只剩环境级提示：
  - `DATABASE_URL_TEST` 未预设，使用 embedded Postgres fallback
  - Docker 不可用，backup/restore 使用本地 `pg_dump` / `pg_restore`

### production readiness

- 最新通过报告：
  `outputs/production_readiness/production_readiness_2026-07-06T06-51-32-596Z_c7c440ff/production_readiness_report.json`
- 结果：
  - total：41
  - passed：41
  - failed：0
  - finalStatus：`NOT_READY`

### 性能复核说明

- 首次 full run：
  `outputs/production_readiness/production_readiness_2026-07-06T06-45-43-285Z_8a18e366/production_readiness_report.json`
  - `PERF-SMOKE` 一次性失败：
    `health_p95_too_high:232.18`
- 随后单独 performance suite 复核通过。
- 随后整套 production readiness 再跑一次，通过。
- 当前结论：
  这次更像环境波动，不是稳定复现的后端功能回归。

## 8. 不改 DDL 的说明

本轮没有改 DDL，也没有扩表，原因是当前问题已经能通过链路收口解决：

- visual export-clean 是 contract / adapter / export path 问题
- English 接入是 adapter / API / runtime 传递问题
- staging 验证是运行方式和验证脚本问题
- `runtime_state_snapshot` 是否主写路径，是运行时行为和测试验证问题

当前 43 张 public 表已经能支撑本轮验证目标。

## 9. 仍需人工确认的问题

- `long_anchor_junior_visual` 这批真实样本本轮没有重新收口，之前 probe 里仍有 formal analysis asset materialization blocker。
- visual batch 的 track metadata 目前仍需外部传入或人工确认；case007 在 staging 中按 `math_junior` 推断。
- local staging cluster 真实使用的是 PostgreSQL 17 安装；如果后续要统一到 18，需要先补齐本机 18 的 `share` 目录。
- production readiness 的性能项本轮出现过一次瞬时波动，虽然后续复核通过，但如果要做更严的生产评审，建议在更干净的机器上再跑一次完整 smoke。
