from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from pathlib import Path


MODULE_ZH = {
    "01_basic_numbers": "基础数与式",
    "02_equation_inequality": "方程与不等式",
    "03_junior_functions": "初中函数",
    "04_plane_geometry": "平面几何",
    "05_sets_logic": "集合与逻辑",
    "06_senior_functions": "高中函数",
    "07_trigonometry": "三角函数",
    "08_analytic_geometry": "解析几何",
    "09_solid_geometry_vectors": "立体几何与向量",
    "10_derivative_complex": "导数、积分与复数",
    "11_sequences": "数列",
    "12_probability_statistics": "概率统计",
}

FAILURE_NOTE_OVERRIDES = {
    "case_011": "源图/切片问题，不计为转录内容错误。",
    "case_035": "几何证明链中关键关系录错，源图应为“EG=AC”，当前结果混入错误关系。",
    "case_040": "字段包装问题，不计为题目内容录错。",
    "case_139": "上游题块污染/越界，不计为转录内容错误。",
    "case_107": "源题内部冲突，已排除出模型错误统计。",
}

CONTENT_FAILURE_CASES = {
    "case_035",
}


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def esc(text: object) -> str:
    return html.escape(str(text or ""))


def badge(label: str, tone: str) -> str:
    return f'<span class="badge badge-{tone}">{esc(label)}</span>'


def text_panel(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return '<div class="text-panel empty">空</div>'
    return f'<div class="text-panel">{esc(value)}</div>'


def format_int(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{int(value):,}"
    return "-"


def format_seconds(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.3f}s"
    return "-"


def module_label(module_en: str) -> str:
    if module_en in MODULE_ZH:
        return f"{MODULE_ZH[module_en]} / {module_en}"
    return module_en or "未标注"


def case_issue_bucket(case_id: str, rejudge_bucket: str, review_reasons: list[str]) -> str:
    if case_id == "case_035":
        return "几何关系录错"
    if "answer_subquestion_count_mismatch" in review_reasons:
        return "子问答案结构风险"
    if "answer_only_long_text" in review_reasons:
        return "答案字段过长风险"
    if "geometry_proof_dense_risk" in review_reasons:
        return "几何长证明高风险"
    if "high_risk_span_density" in review_reasons:
        return "公式/符号高风险密集"
    if "analysis_leading_non_analysis_stripped" in review_reasons:
        return "字段边界切分风险"
    return "其他待复核风险"


def binary_status_from_rejudge(case_id: str, rejudge_bucket: str) -> tuple[str, str]:
    if case_id in CONTENT_FAILURE_CASES:
        return "failure", "确认题目内容录错"
    if rejudge_bucket == "source_internal_conflict":
        return "success", "成功根据数学格式进行转录"
    return "success", "成功根据数学格式进行转录"


def build_binary_records(
    run_results: dict,
    gold_rows: list[dict],
    assessment: dict,
    rejudge: dict,
) -> dict:
    run_map = {item.get("record_id", ""): item for item in run_results.get("records", []) or []}
    gold_map = {item.get("case_id", ""): item for item in gold_rows}
    rejudge_map = {item.get("case_id", ""): item for item in rejudge.get("records", []) or []}
    assessment_map = {item.get("case_id", ""): item for item in assessment.get("records", []) or []}

    records: list[dict] = []
    for case_id, run_item in run_map.items():
        gold = gold_map.get(case_id, {})
        trans = run_item.get("transcription", {}) or {}
        display = trans.get("display_normalized_text", {}) or {}
        assess = assessment_map.get(case_id, {})
        rej = rejudge_map.get(case_id, {})

        module_en = str(gold.get("module_en", "") or assess.get("module", "") or run_item.get("tag", "") or "")
        review_reasons = list(rej.get("review_reasons", []) or assess.get("review_reasons", []) or [])
        rejudge_bucket = str(rej.get("eval_bucket", "") or "")

        if rejudge_bucket:
            binary_status, binary_note = binary_status_from_rejudge(case_id, rejudge_bucket)
        else:
            binary_status, binary_note = "success", "成功根据数学格式进行转录"

        issue_bucket = case_issue_bucket(case_id, rejudge_bucket, review_reasons) if binary_status == "failure" else ""
        if case_id in FAILURE_NOTE_OVERRIDES:
            binary_note = FAILURE_NOTE_OVERRIDES[case_id]

        records.append(
            {
                "case_id": case_id,
                "question_id": run_item.get("question_id", case_id),
                "module_en": module_en,
                "module_zh": MODULE_ZH.get(module_en, ""),
                "module_label": module_label(module_en),
                "binary_status": binary_status,
                "binary_note": binary_note,
                "issue_bucket": issue_bucket,
                "review_reasons": review_reasons,
                "latency_seconds": run_item.get("latency_seconds"),
                "total_tokens": ((run_item.get("usage") or {}).get("total_tokens")),
                "question_image": run_item.get("question_image", "") or gold.get("question_image", "") or gold.get("image_path", ""),
                "model_stem_text_md": str(display.get("stem_text_md", "") or trans.get("stem_text_md", "")),
                "model_answer_text_md": str(display.get("answer_text_md", "") or trans.get("answer_text_md", "")),
                "model_analysis_text_md": str(display.get("analysis_text_md", "") or trans.get("analysis_text_md", "")),
                "gold_stem_text_md": str(gold.get("gold_stem_text_md", "") or ""),
                "gold_answer_text_md": str(gold.get("gold_answer_text_md", "") or ""),
                "gold_analysis_text_md": str(gold.get("gold_analysis_text_md", "") or ""),
                "source_issue": str(gold.get("source_issue", "") or ""),
            }
        )

    records.sort(key=lambda item: (item["binary_status"] != "failure", item["module_en"], item["case_id"]))
    summary = Counter(item["binary_status"] for item in records)
    return {"summary": dict(summary), "records": records}


def build_flow_mermaid() -> str:
    return """
flowchart TD
    A["1. skill 入口<br/>teacher-handout-visual-split-vision-primary"]
    B["2. wrapper 找到仓库 runtime"]
    C["3. 主入口<br/>teacher_pdf_visual_runtime_vision_primary.py"]
    D{"4. 只拆题？"}
    E["5. 视觉拆讲义 stage"]
    E1["5.1 PDF 渲染页面图"]
    E2["5.2 锚点识别 / profile 判定"]
    E3["5.3 组件分组 / 题块归属"]
    E4["5.4 题目切片 / 跨页拼接"]
    E5["5.5 导出 split 产物"]
    F{"6. 是否启用视觉转录？"}
    G["7. 构建 manifest / question_id 清单"]
    H["8. 读取 YAML prompt"]
    I["9. 打包题图 / 题干图 / 解析图"]
    J["10. Doubao 视觉转录"]
    K["11. JSON 解析与修复"]
    L["12. 安全归一化"]
    M["13. 结构映射"]
    N["14. risk span 检测"]
    O["15. quality gate<br/>allow / allow_with_review / block"]
    P["16. 结果落盘"]
    Q["17. 评估与人工审核层"]
    R["18. 可选局部 refine 支线"]

    A --> B --> C --> D
    D -- "否" --> E
    D -- "是" --> F
    E --> E1 --> E2 --> E3 --> E4 --> E5 --> F
    F -- "否" --> P
    F -- "是" --> G --> H --> I --> J --> K --> L --> M --> N --> O --> P --> Q
    O -. "高风险题可走局部精修" .-> R
    R -. "回写修正字段" .-> P
"""


def percent(part: int, total: int) -> str:
    if total <= 0:
        return "0.00%"
    return f"{part / total * 100:.2f}%"


def build_module_distribution_rows(records: list[dict]) -> str:
    buckets = defaultdict(lambda: {"total": 0, "success": 0, "failure": 0})
    for item in records:
        key = item["module_label"]
        buckets[key]["total"] += 1
        buckets[key][item["binary_status"]] += 1

    rows: list[str] = []
    for module, values in sorted(buckets.items(), key=lambda pair: pair[0]):
        rows.append(
            "<tr>"
            f"<td>{esc(module)}</td>"
            f"<td>{values['total']}</td>"
            f"<td>{values['success']}</td>"
            f"<td>{values['failure']}</td>"
            f"<td>{percent(values['success'], values['total'])}</td>"
            "</tr>"
        )
    return "".join(rows)


def build_failure_point_rows(records: list[dict]) -> str:
    failures = [item for item in records if item["binary_status"] == "failure"]
    if not failures:
        return '<tr><td colspan="5">当前没有确认的题目内容转录错误。</td></tr>'

    rows: list[str] = []
    for item in failures:
        rows.append(
            "<tr>"
            f"<td>{esc(item['case_id'])}</td>"
            f"<td>{esc(item['module_label'])}</td>"
            f"<td>{esc(item.get('issue_bucket', '') or '内容转录错误')}</td>"
            f"<td>{esc(item.get('binary_note', ''))}</td>"
            f"<td>{format_int(item.get('total_tokens'))} / {format_seconds(item.get('latency_seconds'))}</td>"
            "</tr>"
        )
    return "".join(rows)


def base_html(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(title)}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css" />
  <style>
    :root {{
      --bg: #f6f1e6;
      --panel: #fffdf8;
      --line: #e4dccd;
      --ink: #1f2937;
      --muted: #6b7280;
      --green: #186048;
      --green-bg: #ddf3e8;
      --red: #9f2d21;
      --red-bg: #f8ddd6;
      --gold: #8a6212;
      --gold-bg: #f5eccd;
      --blue: #255a88;
      --blue-bg: #dcebfa;
      --shadow: 0 12px 30px rgba(54, 34, 12, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 0% 0%, rgba(37,90,136,0.08), transparent 24%),
        radial-gradient(circle at 100% 0%, rgba(159,45,33,0.08), transparent 26%),
        linear-gradient(180deg, #faf7f0 0%, var(--bg) 100%);
    }}
    .wrap {{
      width: min(1540px, calc(100vw - 36px));
      margin: 0 auto;
      padding: 24px 0 48px;
    }}
    .hero {{
      background: linear-gradient(135deg, #7e241b, #3f1b16);
      color: #fff9f5;
      padding: 28px 30px;
      border-radius: 24px;
      box-shadow: var(--shadow);
    }}
    .hero h1 {{
      margin: 0 0 10px;
      font-size: 34px;
    }}
    .hero p {{
      margin: 0;
      line-height: 1.8;
      color: rgba(255,249,245,0.92);
    }}
    .section {{
      margin-top: 22px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 22px 24px;
      box-shadow: var(--shadow);
    }}
    .section h2 {{
      margin: 0 0 14px;
      font-size: 24px;
    }}
    .lead {{
      margin: 0 0 16px;
      color: var(--muted);
      line-height: 1.75;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin-top: 20px;
    }}
    .stat {{
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px 18px;
    }}
    .stat-label {{ color: var(--muted); font-size: 13px; margin-bottom: 6px; }}
    .stat-value {{ font-size: 30px; font-weight: 700; color: var(--red); }}
    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      margin-right: 6px;
      margin-bottom: 6px;
      border: 1px solid transparent;
    }}
    .badge-success {{ background: var(--green-bg); color: var(--green); border-color: #bddfcf; }}
    .badge-failure {{ background: var(--red-bg); color: var(--red); border-color: #e7b2a9; }}
    .badge-warn {{ background: var(--gold-bg); color: var(--gold); border-color: #e6d19e; }}
    .badge-soft {{ background: var(--blue-bg); color: var(--blue); border-color: #bfd8ee; }}
    .grid-2 {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      border-radius: 14px;
      overflow: hidden;
    }}
    th, td {{
      padding: 10px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      line-height: 1.65;
      font-size: 14px;
    }}
    th {{
      background: #fbf7ef;
      color: var(--muted);
      font-weight: 700;
    }}
    .chart-box, .mermaid-box {{
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      min-height: 360px;
    }}
    .chart-box canvas {{ width: 100% !important; height: 320px !important; }}
    details.case {{
      border: 1px solid var(--line);
      border-radius: 18px;
      background: #fffdfa;
      margin-bottom: 14px;
      overflow: hidden;
    }}
    details.case summary {{
      list-style: none;
      cursor: pointer;
      padding: 14px 16px;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
      background: #fdf9f2;
    }}
    details.case summary::-webkit-details-marker {{ display: none; }}
    .summary-main {{ font-weight: 700; }}
    .summary-sub {{ color: var(--muted); font-weight: 500; margin-top: 4px; }}
    .case-body {{ padding: 16px; }}
    .case-grid {{
      display: grid;
      grid-template-columns: minmax(260px, 30%) 1fr 1fr;
      gap: 14px;
      align-items: start;
    }}
    .img-box {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 8px;
      background: #f8f4ec;
    }}
    .img-box img {{ width: 100%; display: block; border-radius: 10px; }}
    .panel {{
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
      background: #fff;
    }}
    .panel h3 {{
      margin: 0;
      padding: 10px 12px;
      background: #fbf7ef;
      color: var(--muted);
      font-size: 13px;
      border-bottom: 1px solid var(--line);
    }}
    .field {{
      border-top: 1px solid var(--line);
    }}
    .field:first-child {{ border-top: 0; }}
    .field-title {{
      padding: 8px 12px;
      background: #fffdfa;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      border-bottom: 1px solid var(--line);
    }}
    .text-panel {{
      padding: 12px;
      white-space: pre-wrap;
      line-height: 1.8;
      font-size: 14px;
    }}
    .text-panel.empty {{ color: var(--muted); }}
    .note {{
      margin-bottom: 12px;
      color: #4b5563;
      line-height: 1.75;
    }}
    @media (max-width: 1180px) {{
      .grid-2, .case-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
{body}
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
  mermaid.initialize({{
    startOnLoad: true,
    theme: 'base',
    themeVariables: {{
      primaryColor: '#f8ddd6',
      primaryBorderColor: '#9f2d21',
      primaryTextColor: '#1f2937',
      lineColor: '#9f2d21',
      secondaryColor: '#dcebfa',
      tertiaryColor: '#ddf3e8',
      fontFamily: 'Microsoft YaHei, PingFang SC, sans-serif'
    }}
  }});
  window.addEventListener('DOMContentLoaded', () => {{
    renderMathInElement(document.body, {{
      delimiters: [
        {{ left: '$$', right: '$$', display: true }},
        {{ left: '$', right: '$', display: false }}
      ],
      throwOnError: false
    }});
  }});
</script>
</body>
</html>"""


def build_analysis_html(bundle: dict, run_results: dict) -> str:
    records = bundle["records"]
    summary = Counter(item["binary_status"] for item in records)
    module_counts = defaultdict(lambda: {"success": 0, "failure": 0})
    issue_counts = Counter()
    for item in records:
        module_counts[item["module_label"]][item["binary_status"]] += 1
        if item["binary_status"] == "failure":
            issue_counts[item["issue_bucket"]] += 1

    module_labels = list(module_counts.keys())
    module_success = [module_counts[key]["success"] for key in module_labels]
    module_failure = [module_counts[key]["failure"] for key in module_labels]
    issue_labels = list(issue_counts.keys())
    issue_values = [issue_counts[key] for key in issue_labels]
    usage = run_results.get("usage_totals", {}) or {}
    latency = run_results.get("latency_summary", {}) or {}
    total = len(records)
    success_count = summary.get("success", 0)
    failure_count = summary.get("failure", 0)
    module_count = len({item["module_label"] for item in records})

    body = f"""
<div class="wrap">
  <section class="hero">
    <h1>流程图 + 结果分析图</h1>
    <p>这份页面把当前 skill 主链路和 200 题二分类结果放在一起。success 表示成功根据数学格式进行转录；failure 表示确认把题目内容本身录错。</p>
  </section>

  <section class="stats">
    <div class="stat"><div class="stat-label">总题量</div><div class="stat-value">{len(records)}</div></div>
    <div class="stat"><div class="stat-label">成功</div><div class="stat-value">{summary.get('success', 0)}</div></div>
    <div class="stat"><div class="stat-label">失败</div><div class="stat-value">{summary.get('failure', 0)}</div></div>
    <div class="stat"><div class="stat-label">总 tokens</div><div class="stat-value">{format_int(usage.get('total_tokens'))}</div></div>
    <div class="stat"><div class="stat-label">平均耗时</div><div class="stat-value">{format_seconds(latency.get('avg_seconds'))}</div></div>
  </section>

  <section class="section">
    <h2>当前 skill 流转图</h2>
    <p class="lead">生产主干是“视觉拆讲义 -> 视觉转录 -> 安全归一化 -> 质量门控 -> 落盘”，评估和人工审查已经挂在后面，不再混进生产主链。</p>
    <div class="mermaid-box"><pre class="mermaid">{esc(build_flow_mermaid())}</pre></div>
  </section>

  <section class="section">
    <h2>图表分析</h2>
    <p class="lead">左图看题目来源知识点分布下的 success / failure，右图看当前失败题按问题类型的构成。</p>
    <div class="grid-2">
      <div class="chart-box"><canvas id="moduleChart"></canvas></div>
      <div class="chart-box"><canvas id="issueChart"></canvas></div>
    </div>
  </section>

  <section class="section">
    <h2>二分类口径说明</h2>
    <table>
      <thead><tr><th>状态</th><th>数量</th><th>当前定义</th></tr></thead>
      <tbody>
        <tr><td>{badge('success', 'success')}</td><td>{summary.get('success', 0)}</td><td>成功根据数学格式进行转录。</td></tr>
        <tr><td>{badge('failure', 'failure')}</td><td>{summary.get('failure', 0)}</td><td>确认模型把题目内容本身录错。</td></tr>
      </tbody>
    </table>
  </section>
</div>
<script>
const moduleLabels = {json.dumps(module_labels, ensure_ascii=False)};
const moduleSuccess = {json.dumps(module_success, ensure_ascii=False)};
const moduleFailure = {json.dumps(module_failure, ensure_ascii=False)};
const issueLabels = {json.dumps(issue_labels, ensure_ascii=False)};
const issueValues = {json.dumps(issue_values, ensure_ascii=False)};

new Chart(document.getElementById('moduleChart'), {{
  type: 'bar',
  data: {{
    labels: moduleLabels,
    datasets: [
      {{ label: 'success', data: moduleSuccess, backgroundColor: '#8ecfae', borderColor: '#186048', borderWidth: 1 }},
      {{ label: 'failure', data: moduleFailure, backgroundColor: '#e6a497', borderColor: '#9f2d21', borderWidth: 1 }}
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    scales: {{
      x: {{ stacked: true, ticks: {{ maxRotation: 60, minRotation: 35 }} }},
      y: {{ stacked: true, beginAtZero: true }}
    }},
    plugins: {{
      legend: {{ position: 'top' }},
      title: {{ display: true, text: '按题目来源知识点的 success / failure 分布' }}
    }}
  }}
}});

new Chart(document.getElementById('issueChart'), {{
  type: 'bar',
  data: {{
    labels: issueLabels,
    datasets: [
      {{ label: 'failure count', data: issueValues, backgroundColor: '#f0c97a', borderColor: '#8a6212', borderWidth: 1 }}
    ]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    scales: {{
      x: {{ beginAtZero: true }}
    }},
    plugins: {{
      legend: {{ display: false }},
      title: {{ display: true, text: '当前 failure 的问题构成' }}
    }}
  }}
}});
</script>
"""
    return base_html("流程图与分析图", body)


def build_analysis_html(bundle: dict, run_results: dict) -> str:
    records = bundle["records"]
    summary = Counter(item["binary_status"] for item in records)
    module_counts = defaultdict(lambda: {"success": 0, "failure": 0})
    issue_counts = Counter()
    for item in records:
        module_counts[item["module_label"]][item["binary_status"]] += 1
        if item["binary_status"] == "failure":
            issue_counts[item["issue_bucket"]] += 1

    module_labels = list(module_counts.keys())
    module_success = [module_counts[key]["success"] for key in module_labels]
    module_failure = [module_counts[key]["failure"] for key in module_labels]
    issue_labels = list(issue_counts.keys())
    issue_values = [issue_counts[key] for key in issue_labels]
    usage = run_results.get("usage_totals", {}) or {}
    latency = run_results.get("latency_summary", {}) or {}
    total = len(records)
    success_count = summary.get("success", 0)
    failure_count = summary.get("failure", 0)
    module_count = len({item["module_label"] for item in records})

    body = f"""
<div class="wrap">
  <section class="hero">
    <h1>流程图 + 测试集分析</h1>
    <p>这份页面把当前 skill 主链路、200 题测试集画像、知识点来源分布和唯一确认失误点放在一起。这里没有 review 桶，failure 只表示确认把题目内容本身录错。</p>
  </section>

  <section class="stats">
    <div class="stat"><div class="stat-label">总题量</div><div class="stat-value">{total}</div></div>
    <div class="stat"><div class="stat-label">success</div><div class="stat-value">{success_count}</div></div>
    <div class="stat"><div class="stat-label">failure</div><div class="stat-value">{failure_count}</div></div>
    <div class="stat"><div class="stat-label">确认内容错误率</div><div class="stat-value">{percent(failure_count, total)}</div></div>
    <div class="stat"><div class="stat-label">平均耗时</div><div class="stat-value">{format_seconds(latency.get('avg_seconds'))}</div></div>
  </section>

  <section class="section">
    <h2>测试集数据画像</h2>
    <p class="lead">当前测试集共 {total} 题，覆盖 {module_count} 个知识点来源模块。success 表示成功根据数学格式进行转录。</p>
    <div class="grid-2">
      <table>
        <thead><tr><th>指标</th><th>数值</th><th>说明</th></tr></thead>
        <tbody>
          <tr><td>样本总量</td><td>{total}</td><td>本轮数学题库视觉转录测试集。</td></tr>
          <tr><td>success</td><td>{success_count}</td><td>成功根据数学格式进行转录。</td></tr>
          <tr><td>failure</td><td>{failure_count}</td><td>确认题目内容本身录错。</td></tr>
          <tr><td>确认内容错误率</td><td>{percent(failure_count, total)}</td><td>当前口径下的模型转录内容错误率。</td></tr>
          <tr><td>知识点来源模块</td><td>{module_count}</td><td>按测试集 module 统计。</td></tr>
          <tr><td>总 tokens</td><td>{format_int(usage.get('total_tokens'))}</td><td>200 题完整转录调用总消耗。</td></tr>
          <tr><td>平均单题耗时</td><td>{format_seconds(latency.get('avg_seconds'))}</td><td>端到端模型请求平均耗时。</td></tr>
        </tbody>
      </table>
      <table>
        <thead><tr><th>case</th><th>来源模块</th><th>问题类型</th><th>失误说明</th><th>成本</th></tr></thead>
        <tbody>
          {build_failure_point_rows(records)}
        </tbody>
      </table>
    </div>
  </section>

  <section class="section">
    <h2>当前 skill 流转图</h2>
    <p class="lead">生产主干是“视觉拆讲义 -> 视觉转录 -> 安全归一化 -> 质量门控 -> 结果落盘”，评估和人工审核挂在后面，不混进生产主链。</p>
    <div class="mermaid-box"><pre class="mermaid">{esc(build_flow_mermaid())}</pre></div>
  </section>

  <section class="section">
    <h2>图表分析</h2>
    <p class="lead">左图看题目来源知识点分布下的 success / failure，右图看当前 failure 的问题构成。</p>
    <div class="grid-2">
      <div class="chart-box"><canvas id="moduleChart"></canvas></div>
      <div class="chart-box"><canvas id="issueChart"></canvas></div>
    </div>
  </section>

  <section class="section">
    <h2>知识点来源分布表</h2>
    <p class="lead">这张表和上面的柱状图是同一份数据，方便审核人不用悬停图表也能直接看到每个来源模块的题量和失败数。</p>
    <table>
      <thead><tr><th>知识点来源模块</th><th>总题数</th><th>success</th><th>failure</th><th>success rate</th></tr></thead>
      <tbody>
        {build_module_distribution_rows(records)}
      </tbody>
    </table>
  </section>

  <section class="section">
    <h2>二分类口径</h2>
    <table>
      <thead><tr><th>状态</th><th>数量</th><th>当前定义</th></tr></thead>
      <tbody>
        <tr><td>{badge('success', 'success')}</td><td>{success_count}</td><td>成功根据数学格式进行转录。</td></tr>
        <tr><td>{badge('failure', 'failure')}</td><td>{failure_count}</td><td>确认模型把题目内容本身录错。</td></tr>
      </tbody>
    </table>
  </section>
</div>
<script>
const moduleLabels = {json.dumps(module_labels, ensure_ascii=False)};
const moduleSuccess = {json.dumps(module_success, ensure_ascii=False)};
const moduleFailure = {json.dumps(module_failure, ensure_ascii=False)};
const issueLabels = {json.dumps(issue_labels, ensure_ascii=False)};
const issueValues = {json.dumps(issue_values, ensure_ascii=False)};

new Chart(document.getElementById('moduleChart'), {{
  type: 'bar',
  data: {{
    labels: moduleLabels,
    datasets: [
      {{ label: 'success', data: moduleSuccess, backgroundColor: '#8ecfae', borderColor: '#186048', borderWidth: 1 }},
      {{ label: 'failure', data: moduleFailure, backgroundColor: '#e6a497', borderColor: '#9f2d21', borderWidth: 1 }}
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    scales: {{
      x: {{ stacked: true, ticks: {{ maxRotation: 60, minRotation: 35 }} }},
      y: {{ stacked: true, beginAtZero: true }}
    }},
    plugins: {{
      legend: {{ position: 'top' }},
      title: {{ display: true, text: '按题目来源知识点的 success / failure 分布' }}
    }}
  }}
}});

new Chart(document.getElementById('issueChart'), {{
  type: 'bar',
  data: {{
    labels: issueLabels,
    datasets: [
      {{ label: 'failure count', data: issueValues, backgroundColor: '#f0c97a', borderColor: '#8a6212', borderWidth: 1 }}
    ]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    scales: {{
      x: {{ beginAtZero: true }}
    }},
    plugins: {{
      legend: {{ display: false }},
      title: {{ display: true, text: '当前 failure 的问题构成' }}
    }}
  }}
}});
</script>
"""
    return base_html("流程图与测试集分析", body)


def build_case_html(record: dict, open_by_default: bool = False) -> str:
    image_uri = ""
    if record["question_image"]:
        try:
            image_uri = Path(record["question_image"]).as_uri()
        except ValueError:
            image_uri = ""
    status_badge = badge(record["binary_status"], "success" if record["binary_status"] == "success" else "failure")
    reason_badges = "".join(badge(item, "soft") for item in record.get("review_reasons", []))
    issue_badge = badge(record["issue_bucket"], "warn") if record.get("issue_bucket") else ""
    image_html = (
        f'<div class="img-box"><img src="{image_uri}" alt="{esc(record["case_id"])}" /></div>'
        if image_uri
        else '<div class="img-box">无题图</div>'
    )
    open_attr = " open" if open_by_default else ""
    return f"""
<details class="case"{open_attr}>
  <summary>
    <div>
      <div class="summary-main">{status_badge}{badge(record["case_id"], "soft")} {issue_badge}</div>
      <div class="summary-sub">{esc(record["module_label"])} | tokens {format_int(record["total_tokens"])} | {format_seconds(record["latency_seconds"])}</div>
    </div>
    <div>{reason_badges}</div>
  </summary>
  <div class="case-body">
    <div class="note">{esc(record["binary_note"])}</div>
    <div class="case-grid">
      {image_html}
      <div class="panel">
        <h3>模型结果</h3>
        <div class="field"><div class="field-title">题干</div>{text_panel(record["model_stem_text_md"])}</div>
        <div class="field"><div class="field-title">答案</div>{text_panel(record["model_answer_text_md"])}</div>
        <div class="field"><div class="field-title">解析</div>{text_panel(record["model_analysis_text_md"])}</div>
      </div>
      <div class="panel">
        <h3>人工金标</h3>
        <div class="field"><div class="field-title">题干</div>{text_panel(record["gold_stem_text_md"])}</div>
        <div class="field"><div class="field-title">答案</div>{text_panel(record["gold_answer_text_md"])}</div>
        <div class="field"><div class="field-title">解析</div>{text_panel(record["gold_analysis_text_md"])}</div>
      </div>
    </div>
  </div>
</details>
"""


def build_review_html(bundle: dict, run_results: dict) -> str:
    records = bundle["records"]
    summary = Counter(item["binary_status"] for item in records)
    failures = [item for item in records if item["binary_status"] == "failure"]
    successes = [item for item in records if item["binary_status"] == "success"]
    usage = run_results.get("usage_totals", {}) or {}
    latency = run_results.get("latency_summary", {}) or {}

    failure_cards = "".join(build_case_html(item, open_by_default=True) for item in failures)
    success_cards = "".join(build_case_html(item, open_by_default=False) for item in successes)

    body = f"""
<div class="wrap">
  <section class="hero">
    <h1>200题结果与金标审核页</h1>
    <p>这份页面已经去掉 review 桶，全部压成 success / failure。success 表示成功根据数学格式进行转录；failure 表示确认把题目内容录错，公式会直接渲染，方便人工逐字段看模型结果与金标。</p>
  </section>

  <section class="stats">
    <div class="stat"><div class="stat-label">总题量</div><div class="stat-value">{len(records)}</div></div>
    <div class="stat"><div class="stat-label">success</div><div class="stat-value">{summary.get('success', 0)}</div></div>
    <div class="stat"><div class="stat-label">failure</div><div class="stat-value">{summary.get('failure', 0)}</div></div>
    <div class="stat"><div class="stat-label">总 tokens</div><div class="stat-value">{format_int(usage.get('total_tokens'))}</div></div>
    <div class="stat"><div class="stat-label">平均耗时</div><div class="stat-value">{format_seconds(latency.get('avg_seconds'))}</div></div>
  </section>

  <section class="section">
    <h2>二分类结果说明</h2>
    <p class="lead">这里不再展示 review。所有题都归成 success 或 failure 两类，failure 只保留确认的内容转录错误。</p>
    <table>
      <thead><tr><th>状态</th><th>数量</th><th>说明</th></tr></thead>
      <tbody>
        <tr><td>{badge('success', 'success')}</td><td>{summary.get('success', 0)}</td><td>成功根据数学格式进行转录。</td></tr>
        <tr><td>{badge('failure', 'failure')}</td><td>{summary.get('failure', 0)}</td><td>确认模型把题目内容本身录错。</td></tr>
      </tbody>
    </table>
  </section>

  <section class="section">
    <h2>Failure 样本</h2>
    <p class="lead">这部分默认展开，优先给人工看最需要盯的题。</p>
    {failure_cards}
  </section>

  <section class="section">
    <h2>Success 样本</h2>
    <p class="lead">success 也保留全量结果，默认折叠，后面如果要抽检可以直接展开。</p>
    {success_cards}
  </section>
</div>
"""
    return base_html("200题结果与金标审核页", body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build binary success/failure review HTML bundle for 200-question audit.")
    parser.add_argument("--run-json", required=True)
    parser.add_argument("--gold-json", required=True)
    parser.add_argument("--assessment-json", required=True)
    parser.add_argument("--rejudge-json", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    run_results = read_json(Path(args.run_json).resolve())
    gold_rows = read_json(Path(args.gold_json).resolve())
    assessment = read_json(Path(args.assessment_json).resolve())
    rejudge = read_json(Path(args.rejudge_json).resolve())
    out_dir = Path(args.out_dir).resolve()
    ensure_dir(out_dir)

    bundle = build_binary_records(run_results, gold_rows, assessment, rejudge)

    binary_json_path = out_dir / "binary_success_failure_200.json"
    analysis_html_path = out_dir / "skill_flow_and_analysis.html"
    review_html_path = out_dir / "gold_vs_result_200_review.html"

    binary_json_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    analysis_html_path.write_text(build_analysis_html(bundle, run_results), encoding="utf-8")
    review_html_path.write_text(build_review_html(bundle, run_results), encoding="utf-8")

    print(
        json.dumps(
            {
                "binary_json": str(binary_json_path),
                "analysis_html": str(analysis_html_path),
                "review_html": str(review_html_path),
                "success_count": bundle["summary"].get("success", 0),
                "failure_count": bundle["summary"].get("failure", 0),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
