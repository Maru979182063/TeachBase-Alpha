# Pipeline Baseline Candidate Discovery 20260714
## Real Status
- Discovery used existing files under `out/`, `outputs/`, and `docs/reports`.
- No live model call was made.
- Deterministic and live model references are separated.

## Selected Candidates
### deterministic_english_mock_p5_6_coordinate_v2
- Category: `deterministic_ci_hard_gate`
- Baseline type: `deterministic`
- Input path: `C:\Users\EDY\Documents\WXWork\1688857912801359\WeDrive\领世培优\领世一对一英语学科资料\高中英语\01标准化讲义\01暑假标准化讲义\高二暑假\语法\词法和句法基础梳理-教师版.pdf`
- Input exists: `True`
- Input hash: `cbcb8dfd6e4f11b9ccba00560e2e5d7377326e37570d31fef4b3ed52ae34fa45`
- Run root: `out/quick_debug_mock/english_p5_6_coordinate_v2`
- Summary: `out/quick_debug_mock/english_p5_6_coordinate_v2/quick_debug_result.json`
- Provider/model: `mock` / ``
- Paid VLM used: `False`; calls: `0`
- Run time from summary mtime: `2026-07-08T06:42:27.037422+00:00`
- Completeness: `3/4` core artifacts present: `semantic_nodes, audit_report, legacy_bridge_questions`
- Metrics: `{"node_summary": {"ready": 7, "needs_review": 0, "quarantined": 1, "question_nodes": 7, "knowledge_nodes": 0, "multi_fragment_nodes": 1}, "refined_node_summary": null, "block_count": 51, "reading_block_count": 9, "node_count": 8, "legacy_bridge_ready_count": 7, "review_repair_pool_count": null, "cross_page_nodes": null}`
- Recommendation: `selected_for_deterministic_baseline`
- Reason: Mock run, input PDF exists, no paid VLM calls, has semantic_nodes/audit_report/legacy_bridge; review_repair_pool is absent so scope is frozen as minimal hard gate.
- Reconstructed command: `python tools/split_v03_quick_debug.py --pdf "C:\Users\EDY\Documents\WXWork\1688857912801359\WeDrive\领世培优\领世一对一英语学科资料\高中英语\01标准化讲义\01暑假标准化讲义\高二暑假\语法\词法和句法基础梳理-教师版.pdf" --doc-key english --pages 5,6 --out out/quick_debug_mock/english_p5_6_coordinate_v2 --provider mock --max-vlm-calls 0`

### live_math_full_handout_concurrent_20260709
- Category: `math_stable_whole_handout`
- Baseline type: `live_model_reference`
- Input path: `C:\Users\EDY\Documents\WXWork\1688857912801359\WeDrive\领世培优\领世一对一数学学科资料\高中数学\01标准化讲义\01 暑假\02 高二\第2讲 解三角形综合\解三角形综合 - 教师版.pdf`
- Input exists: `True`
- Input hash: `49f07c1b6bb09f0d1f38c8f32c6419dcfa2c4e283aaa0410b698a78b3d898220`
- Run root: `out/full_handout_regression_20260709/full_math_english_concurrent_20260709/math`
- Summary: `out/full_handout_regression_20260709/full_math_english_concurrent_20260709/math/full_doc_run_summary.json`
- Provider/model: `visual` / `doubao-seed-2-0-lite-260428`
- Paid VLM used: `True`; calls: `13`
- Run time from summary mtime: `2026-07-09T05:59:53.348496+00:00`
- Completeness: `4/4` core artifacts present: `semantic_nodes, audit_report, legacy_bridge_questions, review_repair_pool`
- Metrics: `{"node_summary": {"ready": 40, "needs_review": 11, "quarantined": 1, "question_nodes": 47, "knowledge_nodes": 4, "multi_fragment_nodes": 26, "cross_page_nodes": 21}, "refined_node_summary": {"ready": 47, "needs_review": 4, "quarantined": 1, "question_nodes": 47, "knowledge_nodes": 4, "multi_fragment_nodes": 26, "cross_page_nodes": 21}, "block_count": null, "reading_block_count": null, "node_count": null, "legacy_bridge_ready_count": 40, "review_repair_pool_count": 12, "cross_page_nodes": 21}`
- Recommendation: `selected_for_live_reference`
- Reason: Full math handout, input PDF exists, visual provider/model recorded, complete core artifacts and cross-page metrics present.
- Reconstructed command: `python tools/run_split_v03_full_doc.py --pdf "C:\Users\EDY\Documents\WXWork\1688857912801359\WeDrive\领世培优\领世一对一数学学科资料\高中数学\01标准化讲义\01 暑假\02 高二\第2讲 解三角形综合\解三角形综合 - 教师版.pdf" --doc-key math --out out/full_handout_regression_20260709/full_math_english_concurrent_20260709/math --provider visual --model doubao-seed-2-0-lite-260428 --max-vlm-calls 132 --refine`

### live_english_full_handout_concurrent_20260709
- Category: `english_whole_handout`
- Baseline type: `live_model_reference`
- Input path: `C:\Users\EDY\Documents\WXWork\1688857912801359\WeDrive\领世培优\领世一对一英语学科资料\高中英语\01标准化讲义\01暑假标准化讲义\高三暑假\语法\高考一轮之必考定语从句1-教师版.pdf`
- Input exists: `True`
- Input hash: `4a1599454799f6702ff0a734b612df28fdaff18e4b2903d60052a0cd9f59bbde`
- Run root: `out/full_handout_regression_20260709/full_math_english_concurrent_20260709/english`
- Summary: `out/full_handout_regression_20260709/full_math_english_concurrent_20260709/english/full_doc_run_summary.json`
- Provider/model: `visual` / `doubao-seed-2-0-lite-260428`
- Paid VLM used: `True`; calls: `16`
- Run time from summary mtime: `2026-07-09T05:56:51.246569+00:00`
- Completeness: `4/4` core artifacts present: `semantic_nodes, audit_report, legacy_bridge_questions, review_repair_pool`
- Metrics: `{"node_summary": {"ready": 49, "needs_review": 22, "quarantined": 0, "question_nodes": 56, "knowledge_nodes": 15, "multi_fragment_nodes": 13, "cross_page_nodes": 11}, "refined_node_summary": {"ready": 55, "needs_review": 15, "quarantined": 0, "question_nodes": 55, "knowledge_nodes": 15, "multi_fragment_nodes": 15, "cross_page_nodes": 13}, "block_count": null, "reading_block_count": null, "node_count": null, "legacy_bridge_ready_count": 49, "review_repair_pool_count": 22, "cross_page_nodes": 11}`
- Recommendation: `selected_for_live_reference`
- Reason: Full English handout, input PDF exists, visual provider/model recorded, complete core artifacts and cross-page metrics present.
- Reconstructed command: `python tools/run_split_v03_full_doc.py --pdf "C:\Users\EDY\Documents\WXWork\1688857912801359\WeDrive\领世培优\领世一对一英语学科资料\高中英语\01标准化讲义\01暑假标准化讲义\高三暑假\语法\高考一轮之必考定语从句1-教师版.pdf" --doc-key english --out out/full_handout_regression_20260709/full_math_english_concurrent_20260709/english --provider visual --model doubao-seed-2-0-lite-260428 --max-vlm-calls 112 --refine`

### live_biology_edge_crosspage_20260709
- Category: `edge_cross_page_long_visual_sample`
- Baseline type: `live_model_reference`
- Input path: `C:\Users\EDY\Documents\WXWork\1688857912801359\WeDrive\领世培优\领世一对一生物学科资料\01标准化讲义\暑假\02高二讲义\专题强化之遗传的基本规律和人类遗传病\第2讲 伴性遗传\伴性遗传(教师版).pdf`
- Input exists: `True`
- Input hash: `2851749d694955b00a0e5acc7ff3e8706402e67d5f508613840521c055452a8a`
- Run root: `out/full_handout_regression_20260709/bio`
- Summary: `out/full_handout_regression_20260709/bio/quick_debug_result.json`
- Provider/model: `visual` / `doubao-seed-2-0-lite-260428`
- Paid VLM used: `True`; calls: `39`
- Run time from summary mtime: `2026-07-08T18:18:05.182065+00:00`
- Completeness: `4/4` core artifacts present: `semantic_nodes, audit_report, legacy_bridge_questions, review_repair_pool`
- Metrics: `{"node_summary": {"ready": 34, "needs_review": 25, "quarantined": 0, "question_nodes": 41, "knowledge_nodes": 18, "multi_fragment_nodes": 24, "cross_page_nodes": 23}, "refined_node_summary": null, "block_count": 84, "reading_block_count": 84, "node_count": 59, "legacy_bridge_ready_count": 34, "review_repair_pool_count": 25, "cross_page_nodes": 23}`
- Recommendation: `selected_as_edge_candidate_not_hard_gate`
- Reason: Long biology run with 23 cross-page nodes and complete core artifacts; live model output only, suitable as edge reference, not CI hash gate.
- Reconstructed command: `python tools/split_v03_quick_debug.py --pdf "C:\Users\EDY\Documents\WXWork\1688857912801359\WeDrive\领世培优\领世一对一生物学科资料\01标准化讲义\暑假\02高二讲义\专题强化之遗传的基本规律和人类遗传病\第2讲 伴性遗传\伴性遗传(教师版).pdf" --doc-key bio --pages 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39 --out out/full_handout_regression_20260709/bio --provider visual --model doubao-seed-2-0-lite-260428 --max-vlm-calls 39`

## Noted Limitations
- The deterministic candidate lacks `review_repair_pool.json`; it is frozen only as a minimal hard-gate baseline, not as full PDF production evidence.
- Live model references are existing artifacts and are not suitable for strict CI hash gates.
- Release decision and Runtime import payloads are absent from these split_v03 candidates.
