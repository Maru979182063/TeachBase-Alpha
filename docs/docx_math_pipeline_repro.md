# DOCX Math Native Pipeline Reproduction

这份文档给实习生复现 DOCX native-first 数学题目链路使用。

当前链路目标：从 `.docx` 读取原生 XML / 图片 / 公式资源，生成可人工检查的 refined question packets 和 side-by-side review 包。

当前链路边界：

- 不写数据库。
- 不做 Runtime import。
- 不修改 PDF visual-first 链路。
- 不把 `word/media` 原图压缩或删除。
- legacy Equation Editor 公式恢复失败时会保留 `needs_review` / fallback 信号。

## 1. Branch

```powershell
git fetch origin
git switch codex/docx-native-stage0-router-v01
git pull
```

## 2. Required Dependencies

Python:

```powershell
python --version
```

Node.js:

```powershell
node --version
```

Ruby:

```powershell
ruby --version
```

Model API:

```powershell
$env:ARK_API_KEY="your_ark_api_key"
```

说明：

- `ARK_API_KEY` 用于 block tagger、question grouper、part normalizer、question refiner。
- wrapper 也支持 `--api-key`，但推荐使用环境变量，避免命令历史里暴露 key。

## 3. Optional Formula Dependencies

legacy Equation Editor / OLE 公式恢复需要：

- Ruby gem: `mathtype_to_mathml_plus`
- Node package: `mathml-to-latex`

检查 Ruby 侧：

```powershell
ruby -e "require 'mathtype_to_mathml_plus'; puts 'mathtype_to_mathml_plus ok'"
```

检查 Node 侧：

```powershell
node -e "require('mathml-to-latex'); console.log('mathml-to-latex ok')"
```

如果 Node 包不在项目根 `node_modules`，运行 wrapper 时传：

```powershell
--mathml-node-module-dir "C:\path\to\node_project"
```

## 4. One-command Pipeline

入口脚本：

```powershell
tools\docx_math_pipeline_orchestrator_v01.py
```

教师版 / 解析版通常用：

```powershell
python tools\docx_math_pipeline_orchestrator_v01.py `
  --docx "C:\path\to\your.docx" `
  --run-id "my_docx_run_20260721_v01" `
  --solution-policy-hint required `
  --force-render `
  --clean
```

原卷版 / 无答案文件可用：

```powershell
python tools\docx_math_pipeline_orchestrator_v01.py `
  --docx "C:\path\to\your_original.docx" `
  --run-id "my_docx_original_run_20260721_v01" `
  --solution-policy-hint absent_expected `
  --force-render `
  --clean
```

长文档不想立刻渲染原页对照包时：

```powershell
python tools\docx_math_pipeline_orchestrator_v01.py `
  --docx "C:\path\to\your.docx" `
  --run-id "my_docx_run_20260721_v01" `
  --skip-side-by-side `
  --clean
```

## 5. Pipeline Stages

`docx_native_stage0_router_v01`

中文：DOCX 原生入口。检查 OMML、legacy OLE/MTEF、图片和段落流，输出 Stage0 block stream。

`docx_native_block_tagger_v01`

中文：逐 block 打标签。只判断 block 类型和内容标签，不组题。

`docx_question_grouper_v01`

中文：把连续 block 组合成题包候选。

`membership_adapter`

中文：wrapper 内置胶水层，把 grouper 的 `question_packet_candidates.json` 转成 normalizer 可读的 `membership_groups.json`。

`docx_question_part_normalizer_v01`

中文：一题一题把 block 归一化为题干、选项、小问、答案、解析等 parts。

`docx_math_source_backed_draft_builder_v01`

中文：把 parts 构造成 source-backed draft，保留 source block refs、asset refs、formula counts。

`docx_math_fullchain_orchestrator_v01`

中文：一题一题精修为标准题目字段，支持失败 retry。

`docx_math_build_side_by_side_review_v01`

中文：生成左侧原页、右侧拆出题目的人工验收包。

## 6. Main Artifacts

总控 summary：

```text
outputs/docx_math_pipeline_orchestrator_v0_1/<run_id>/pipeline_summary.json
```

最终题包：

```text
outputs/docx_math_fullchain_orchestrator_v0_1/<run_id>__fullchain/final_packets.json
```

精修预览：

```text
outputs/docx_math_fullchain_orchestrator_v0_1/<run_id>__fullchain/review.html
```

side-by-side 预览：

```text
outputs/docx_math_side_by_side_review_v0_1/<run_id>__side_by_side/index.html
```

side-by-side zip：

```text
outputs/docx_math_side_by_side_review_v0_1/<run_id>__side_by_side.zip
```

## 7. Expected Summary Fields

`pipeline_summary.json` 里重点看：

- `status`: `ok` 或 `needs_review`
- `nodes.stage0_router.status`: Stage0 入口是否有公式 fallback 风险
- `nodes.block_tagger.status`: 打标是否有 resolution
- `nodes.question_grouper.packet_count`: 题包数量
- `nodes.part_normalizer.blocking_issue_count`: parts 归一化是否有阻断
- `nodes.fullchain_refiner.refined_ready_count`: 精修成功题数
- `nodes.fullchain_refiner.blocked_count`: 最终阻断题数
- `artifacts.final_packets`: 最终题包 JSON
- `artifacts.side_by_side_index`: 人工对照页

## 8. Known Risks

- 当前是一条可复现工程链路，不是生产入库链路。
- legacy OLE 公式依赖 Ruby/Node 后端，部署到 Linux 时需要单独安装和 smoke test。
- 大 DOCX 会触发较多模型调用，成本和时延仍需优化。
- Stage0 有 fallback signal 时，不应把结果直接当生产成品。
- side-by-side 原页渲染耗时可能较长，可以先用 `--skip-side-by-side` 跑结构链路。

## 9. Smoke Checks

语法检查：

```powershell
python -m py_compile `
  tools\docx_legacy_formula_recovery_v01.py `
  tools\docx_native_stage0_router_v01.py `
  tools\docx_math_pipeline_orchestrator_v01.py `
  tools\docx_math_question_refiner_v01.py

node --check tools\mathml_to_latex_batch.cjs
ruby -c tools\ruby_mtef_to_mathml_batch.rb
```

检查是否误写入库：

```powershell
Select-String -Path "outputs\docx_math_pipeline_orchestrator_v0_1\<run_id>\pipeline_summary.json" -Pattern "database_write"
```
