# 完整题包到待审核数据库

`POST /api/v1/ingestion/candidate-batches` 将已经加工完成的题包保存为候选，同时通过公开模块端口注册题源、来源区域、题目修订和审核任务。它不调用 Release Seed，也不提交审核决定。

## 边界与事务

- 每批 1–100 题。输入题目仍遵守 `QuestionImportItem`；只允许 `unreviewed`、`pending_review`，模型 READY 不是批准依据。
- 文件字节先由存储适配器持久化，经 `/api/v1/files` 登记；入口验证文件版本、工作空间、SHA-256 一致。
- `sourceKey` 必须以文档 SHA-256 和 `/` 开头，同批不得出现重复来源身份。题目内容及来源关联全部在 Java 单事务内提交，失败整批回滚。
- 题目、不可变修订和导入观察复用已有领域幂等机制。来源区域绑定修订 UUID，重放复用已有来源和开放审核任务；已有终态修订不重新审核。
- 完整教学结构保存在 `content_json`，运行结果、警告、原题包和文件索引放在 provenance。公式字符串不转换。
- 导入成功不意味着展示兼容、语义质量或人工审核通过。搜索默认只返回已批准题目，候选通过 `reviewStatus=pending_review` 检索。

当前是同步有界入口，尚无持久化批次表、后台队列、跨批断点或标准四链 worker；失败可以整批重交。继承现有成员检查，尚未替代项目开放的正式认证与动作权限工作。

## 数学 DOCX 适配

安装 `pip install -e .[dev]`。`tools/import_docx_math_candidates.py` 接收 `--packets`、`--source`、`--asset-map`、`--subject`、`--base-url`、`--workspace-id`、`--actor-user-id`、`--storage-root` 和 `--out-dir`。可重复指定 `--evidence` 保存来源块流等证据。

适配器先校验最终题包结构，再保存原文、原始题包、图片和证据文件，随后登记文件并提交候选。文件按字节 SHA-256 定位，冲突不会覆盖已有数据。文件注册失败或数据库批次回滚后，已保存文件仍保留以便重试。

基础模型 schema 未描述编排器追加的覆盖报告、`READY_WITH_COVERAGE_WARNINGS` 和结构化处理留证。`final_packet_schema()` 显式声明这些最终出口字段；其他未知顶层字段仍被拒绝。新增的覆盖警告状态仍进入待审核，未改变模型输出合同或放行政策。

当前题目没有可靠的跨轮稳定 ID，因此采用 `文档哈希/完整题包文件哈希/题组ID`。相同文件重交幂等；换一轮题包不会凭同序号覆盖旧题。跨轮题目合并和修订归并仍需正式身份契约。

## 本地验证服务

先执行 `node tools/run_java_foundation_maven.mjs -q package`，然后运行：

```text
node tools/run_candidate_ingestion_local.mjs --data-root D:/Projects/TeachBase-Alpha-local-data/candidate-ingestion-20260904
```

服务使用独立 PostgreSQL 端口 15434 和 Java 端口 18084，均仅监听回环地址；数据库名 `teachbase_candidates`。应用启动时执行 Flyway。专用工作空间和本地操作员只用于验证候选导入，不代表真人已审核。

数据目录保存 PostgreSQL 文件、storage、日志和 `runtime.json`。本地生成的随机密码只保存在 `local.private.json`，不能提交或分享该文件。数据库以 persistent 模式运行，停止后不删除。前台终端中输入 `restart` 重启 Java 与数据库，输入 `stop` 停止服务；再次执行启动命令复用数据。

```text
node tools/verify_candidate_ingestion.mjs --data-root D:/Projects/TeachBase-Alpha-local-data/candidate-ingestion-20260904 --receipt-dir outputs/sets_teacher_trial_20260904_5799ab69/database_ingestion
```

验证器只连接这个专属本地库，检查原始题包及 LaTeX 读回、文件字节、来源和审核关联、并发重放、整批回滚、成员隔离及搜索状态隔离。测试生成的无效候选全部回滚，真实题目不批准、不删除。

## 真实数据副本整体测试

安装开发依赖及 `npm run setup:document-renderer`，构建 Java 后执行：

```text
node tools/run_real_candidate_workflow_gate.mjs --source-data-root D:/Projects/TeachBase-Alpha-local-data/candidate-ingestion-20260904 --out-dir artifacts/ci/real-candidate-workflow/my-run
```

`TEACHBASE_PG_BIN` 可以指定 pg_dump/pg_restore 所在目录；`TEACHBASE_QA_PYTHON` 可以指定含 pypdf/Pillow 的 Python。原候选库仅用于只读备份；审批、标签、修订、题篮及导出在独立恢复副本中执行。报告会保留失败并返回非零退出码。当前单主标签不变量会失败，不应忽略该结果。

导出已支持本次 DOCX 结构化选项、子问及同工作空间登记的 PNG/JPEG 图片。引用按 SHA-256 固定图片身份；渲染验证实际字节，不接受任意 URL 或绝对图片路径。数据库中的原始 LaTeX 保持不变，导出 AST 单独适配圈号。
