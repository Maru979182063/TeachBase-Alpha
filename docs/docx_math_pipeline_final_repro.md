# DOCX Math Native Final Pipeline

This document records the isolated final-candidate DOCX math native chain.

中文说明：这里的 **final** 是“当前确认的候选主链”，不是生产入库承诺。该链路默认不写数据库、不执行 Runtime import。

## Entry

解析带答案/解析的 DOCX：

```powershell
python tools\docx_math_pipeline_final_orchestrator_v01.py `
  --docx "C:\path\to\your.docx" `
  --run-id "my_docx_final_run" `
  --solution-policy-hint required `
  --force-render `
  --clean
```

解析原卷版、无答案文件：

```powershell
python tools\docx_math_pipeline_final_orchestrator_v01.py `
  --docx "C:\path\to\your_original.docx" `
  --run-id "my_docx_final_original_run" `
  --solution-policy-hint absent_expected `
  --force-render `
  --clean
```

诊断用绕过 Stage0 fallback 门闸：

```powershell
python tools\docx_math_pipeline_final_orchestrator_v01.py `
  --docx "C:\path\to\your.docx" `
  --run-id "unsafe_diagnostic_run" `
  --stage0-fallback-policy allow `
  --clean
```

中文说明：`--stage0-fallback-policy allow` 只用于诊断，不应用作交付链路；它会允许公式恢复失败的文本继续往下游流。

## Required Dependencies

Python and Node.js are required.

Install Node dependencies from the repository root:

```powershell
npm install
```

Required Node packages:

- `mathml-to-latex`

中文说明：`mathml-to-latex` 是 legacy Equation Editor OLE/MTEF 公式链路的关键依赖。很多旧 DOCX 公式会先恢复成 MathML，再转成 LaTeX。缺这个依赖时，公式会变成空洞文本，例如“圆心为，半径为3米”。Stage0 现在会在 OLE 文档进入恢复前做 preflight；缺依赖会输出 `mathml_to_latex_dependency_missing` 并阻断主链。

Optional dependency path override:

```powershell
$env:MATHML_TO_LATEX_NODE_MODULE_DIR = "C:\path\to\repo"
```

or:

```powershell
python tools\docx_native_stage0_router_v01.py `
  --docx "C:\path\to\your.docx" `
  --run-id "stage0_probe" `
  --mathml-node-module-dir "C:\path\to\repo" `
  --clean
```

## Node Order

1. `docx_native_stage0_router_v01`
   - 中文：DOCX 原生入口；处理 unzip、`word/document.xml`、`word/media`、OMML、legacy OLE/MTEF、普通 run 上下角标数学归一化、段落流和资产清单。
2. `docx_native_block_tagger_v01`
   - 中文：逐 block 粗打标和降噪；不组题。
3. `docx_asset_role_visual_tagger_v01`
   - 中文：视觉图片归属打标；识别题干图、解析图、选项图、栏目图、装饰图、Logo，并把增强后的 block tags 交给后续节点。
4. `docx_question_boundary_cutter_v01`
   - 中文：模型只做题目边界截断，输出 `new_question_starts`、continuation、context、waste；不改写题目内容。
5. `membership_adapter`
   - 中文：程序按边界线性装配，把 `assembled_packets.json` 转成下游 `membership_groups.json`。
6. `docx_question_complexity_router_v01`
   - 中文：把题包路由到普通归一化或长题归一化。
7. `docx_question_part_normalizer_v01` / `docx_question_part_long_normalizer_v01`
   - 中文：把每个题包归一化为题干、小问、选项、答案、解析、点睛等字段。
8. `docx_math_source_backed_draft_builder_v01`
   - 中文：生成带 source block 和 asset refs 的 source-backed draft。
9. `docx_math_fullchain_orchestrator_v01`
   - 中文：逐题精修、gate repair、长复合题精修，输出 review packets。
10. `docx_math_build_side_by_side_review_v01`
   - 中文：可选人工核对包。

## Hard Gates

- Stage0 handoff 必须是 `READY_FOR_BLOCK_TAGGER`，否则 final chain 默认停止。
- Boundary Cutter 的 `unassigned_candidate_block_count` 必须为 `0`。
- Complexity Router 的 `hard_fail` group 直接停止。
- Part Normalizer merge 有 blocking issue 直接停止。
- Runtime import 和 database write 始终关闭。

## Main Artifacts

```text
outputs/docx_math_pipeline_final_v0_1/<run_id>/pipeline_summary.json
outputs/docx_native_stage0_router_v0_1/<run_id>__stage0_router/<doc_id>/handoff_manifest.json
outputs/docx_question_boundary_cutter_v0_1/<run_id>__question_boundary_cutter/<doc_id>/boundary_events.json
outputs/docx_question_boundary_cutter_v0_1/<run_id>__question_boundary_cutter/<doc_id>/assembled_packets.json
outputs/docx_math_fullchain_orchestrator_v0_1/<run_id>__fullchain/final_packets.json
outputs/docx_math_fullchain_orchestrator_v0_1/<run_id>__fullchain/review.html
outputs/docx_math_side_by_side_review_v0_1/<run_id>__side_by_side/index.html
```

## Active Manifest

The canonical active-chain manifest is:

```text
config/docx_math_pipeline_final_active_manifest.json
```

中文说明：后续找入口、节点、输出根目录时，以这个 manifest 为准。历史 `docx_question_grouper`、旧 `docx_math_pipeline_orchestrator`、旧 `docx_native_pipeline` 等不再作为 final 链路入口。

## Obsolete Outputs

Confusing DOCX math/native experiment output roots have been removed from the workspace.
Do not use old experiment roots as final-chain inputs. The active manifest keeps the
old entrypoints and output roots in `do_not_use_as_final` for audit context only.

中文说明：旧实验/探针/旁支产物已经清理，不应再作为当前 final 链路的输入依据。后续复现只看 active manifest 和本文件列出的 final entrypoint。

## Current Boundary

- This is the isolated final-candidate chain.
- It has not been declared production-ready.
- It does not write the database.
- It does not run Runtime import.
- Stage0 now blocks native downstream when formula fallback is required.
- The automatic PDF/visual formula fallback runner is still not implemented.
