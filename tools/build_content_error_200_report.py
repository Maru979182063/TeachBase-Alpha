from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from pathlib import Path


REPORT_TITLE = "200题纯内容转录评估"
CASE_NOTE_OVERRIDES = {
    "case_011": "源图只包含答案与解答区域，题干缺失；当前结果把局部区域误当成整题转录。",
    "case_035": "几何证明链中出现内容性误录，源图里应为“故 EG=AC”，当前结果混入了“EG=EF”等错误关系。",
    "case_040": "这是一道求证题，当前结果把结论直接塞进了答案字段，属于字段级归位错误，不应直接入库。",
    "case_107": "源图内部就存在题干与解析冲突，这类样本不适合拿来统计模型内容错误率。",
    "case_139": "单题切片混入了第5到第7题整段内容，属于明显的题块污染，当前结果不可直接入库。",
}


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def escape(text: object) -> str:
    return html.escape(str(text or ""))


def badge(label: str, tone: str) -> str:
    return f'<span class="badge badge-{tone}">{escape(label)}</span>'


def format_seconds(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.3f}s"
    return "-"


def format_int(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{int(value):,}"
    return "-"


def text_block(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return '<div class="text-block empty">空</div>'
    return f'<div class="text-block">{escape(value)}</div>'


def resolve_case_note(record: dict) -> str:
    case_id = str(record.get("case_id", "") or "")
    if case_id in CASE_NOTE_OVERRIDES:
        return CASE_NOTE_OVERRIDES[case_id]
    return str(record.get("content_error_note", "") or "")


def build_module_rows(records: list[dict]) -> str:
    buckets = defaultdict(Counter)
    for record in records:
        buckets[str(record.get("module", "") or "unlabeled")][record["content_error_status"]] += 1

    rows: list[str] = []
    for module in sorted(buckets):
        counter = buckets[module]
        rows.append(
            "<tr>"
            f"<td>{escape(module)}</td>"
            f"<td>{counter.get('confirmed_transcription_error', 0)}</td>"
            f"<td>{counter.get('no_clear_content_error', 0)}</td>"
            f"<td>{counter.get('needs_manual_recheck', 0)}</td>"
            f"<td>{counter.get('source_issue_excluded', 0)}</td>"
            "</tr>"
        )
    return "".join(rows)


def build_case_card(
    record: dict,
    run_map: dict[str, dict],
    title_tone: str,
) -> str:
    run_record = run_map.get(record["case_id"], {})
    transcription = run_record.get("transcription", {}) or {}
    display = transcription.get("display_normalized_text", {}) or {}
    reasons = record.get("review_reasons", []) or []
    reason_badges = "".join(badge(item, "soft") for item in reasons) or badge("none", "muted")
    image_uri = ""
    raw_path = str(run_record.get("question_image", "") or "")
    if raw_path:
        try:
            image_uri = Path(raw_path).as_uri()
        except ValueError:
            image_uri = ""

    image_html = (
        f'<div class="image-wrap"><img src="{image_uri}" alt="{escape(record["case_id"])}" /></div>'
        if image_uri
        else '<div class="image-wrap empty-image">无题图</div>'
    )

    return (
        '<section class="case-card">'
        '<div class="case-head">'
        f'<div class="case-title">{badge(record["case_id"], title_tone)} '
        f'<span class="module">{escape(record.get("module", "") or "unlabeled")}</span></div>'
        f'<div class="case-meta">{badge(record.get("original_ingest_decision", "-"), "dark")}'
        f'{reason_badges}</div>'
        "</div>"
        f'<div class="case-note">{escape(resolve_case_note(record))}</div>'
        '<div class="case-grid">'
        f"{image_html}"
        '<div class="text-panels">'
        '<div class="panel"><div class="panel-title">题干</div>'
        f"{text_block(str(display.get('stem_text_md', '') or transcription.get('stem_text_md', '')))}</div>"
        '<div class="panel"><div class="panel-title">答案</div>'
        f"{text_block(str(display.get('answer_text_md', '') or transcription.get('answer_text_md', '')))}</div>"
        '<div class="panel"><div class="panel-title">解析</div>'
        f"{text_block(str(display.get('analysis_text_md', '') or transcription.get('analysis_text_md', '')))}</div>"
        "</div>"
        "</div>"
        "</section>"
    )


def build_recheck_rows(records: list[dict]) -> str:
    rows: list[str] = []
    for record in records:
        reasons = " / ".join(record.get("review_reasons", []) or []) or "-"
        rows.append(
            "<tr>"
            f"<td>{escape(record['case_id'])}</td>"
            f"<td>{escape(record.get('module', '') or 'unlabeled')}</td>"
            f"<td>{escape(record.get('original_ingest_decision', ''))}</td>"
            f"<td>{escape(reasons)}</td>"
            "</tr>"
        )
    return "".join(rows)


def build_mermaid_flow() -> str:
    return """
flowchart TD
    A["1. Skill 入口<br/>teacher-handout-visual-split-vision-primary / SKILL.md"]
    B["2. Skill wrapper 定位仓库脚本<br/>skills/.../scripts/teacher_pdf_visual_question_split_v02.py"]
    C["3. 主 runtime 入口<br/>tools/teacher_pdf_visual_runtime_vision_primary.py"]
    D{"4. VISUAL_TRANSCRIBE_ONLY ?"}
    E["5. 视觉拆解 stage<br/>tools/teacher_pdf_visual_question_split_v02.py"]
    E1["5.1 PDF 渲染为页面图"]
    E2["5.2 profile / anchors / 组件锚点识别"]
    E3["5.3 组件分组与题块归属"]
    E4["5.4 题目切片 / 跨页拼接 / crop 导出"]
    E5["5.5 导出 split 结果<br/>teacher_visual_question_transcription_v0.1.json 等"]
    F{"6. VISUAL_TRANSCRIBE_ENABLE ?"}
    G["7. 构建转录任务清单<br/>manifest / source_json / question_ids"]
    H["8. 读取 YAML 提示词<br/>config/teacher_handout_visual_prompts.yaml"]
    I["9. 打包视觉证据<br/>question_image + stem_image + analysis_image + helper hints"]
    J["10. 调用视觉模型转录<br/>tools/teacher_handout_visual_transcribe_doubao.py"]
    K["11. 解析并修复 JSON 响应<br/>extract_json_block / LaTeX 控制字符修复"]
    L["12. 安全归一化<br/>visual_transcription_core.safe_normalize_transcription_payload"]
    M["13. 结构映射<br/>build_structure_mapping"]
    N["14. 风险 span 检测<br/>detect_risk_spans"]
    O["15. 质量门控<br/>build_quality_gate => allow / allow_with_review / block"]
    P["16. 写出结果文件<br/>visual_transcription_results.json / compact / summary"]
    Q["17. 评估与审查层<br/>strict eval / audit html / manual rejudge"]
    R["18. 可选局部精修支线<br/>visual_transcription_local_refine.py<br/>当前 200 题主跑批未接入"]

    A --> B --> C --> D
    D -- "否" --> E
    D -- "是" --> F
    E --> E1 --> E2 --> E3 --> E4 --> E5 --> F
    F -- "否" --> P
    F -- "是" --> G --> H --> I --> J --> K --> L --> M --> N --> O --> P --> Q
    O -. "高风险题可接局部复读" .-> R
    R -. "回写修正字段" .-> P
"""


def build_node_rows() -> str:
    nodes = [
        ("1", "Skill 入口", "选择 visual-first skill，确定这是视觉拆解 + 视觉转录链路。"),
        ("2", "Skill wrapper", "从技能目录跳转到仓库里的真实 runtime 脚本。"),
        ("3", "主 runtime", "读取环境变量，决定跑 split、transcribe，还是只跑其中一段。"),
        ("4", "模式判断", "根据 VISUAL_TRANSCRIBE_ONLY / VISUAL_TRANSCRIBE_ENABLE 选择路径。"),
        ("5", "视觉拆解 stage", "把 PDF 页面切成组件、题块、题图，并确认题块归属。"),
        ("6", "转录开关", "只有打开视觉转录时才会进入模型调用链。"),
        ("7", "任务清单构建", "整理 manifest、source_json、question_id，生成待转录题目列表。"),
        ("8", "YAML 提示词", "从 teacher_handout_visual_prompts.yaml 读取当前 active variant。"),
        ("9", "视觉证据打包", "把整题图、题干图、解析图和 helper hints 一起送进请求。"),
        ("10", "视觉模型转录", "调用 Doubao 视觉模型生成 JSON 字段输出。"),
        ("11", "响应修复", "修复 JSON 包裹、转义、LaTeX 控制字符等常见响应问题。"),
        ("12", "安全归一化", "轻量清洗格式，不让后处理越界改内容。"),
        ("13", "结构映射", "把题干 / 答案 / 解析字段映射成结构化 block。"),
        ("14", "风险 span 检测", "标记高风险公式、几何符号、可疑 span。"),
        ("15", "质量门控", "输出 allow / allow_with_review / block，用于入库决策。"),
        ("16", "结果落盘", "写 visual_transcription_results.json、compact 和 summary。"),
        ("17", "评估审查层", "严格比对、人工复判、审查页都在这一层，不回写生产主干。"),
        ("18", "局部精修支线", "保留了 local refine 方案，但当前 200 题主跑批未接入。"),
    ]
    return "".join(
        "<tr>"
        f"<td>{escape(idx)}</td>"
        f"<td>{escape(name)}</td>"
        f"<td>{escape(desc)}</td>"
        "</tr>"
        for idx, name, desc in nodes
    )


def html_shell(body: str, title: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <link rel="preconnect" href="https://cdn.jsdelivr.net" />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css" />
  <style>
    :root {{
      --bg: #f7f3ea;
      --panel: #fffdf9;
      --ink: #1f2937;
      --muted: #6b7280;
      --line: #e5dccb;
      --brand: #8f2d22;
      --brand-soft: #f8dfd9;
      --gold: #9a6b16;
      --gold-soft: #f6edd2;
      --green: #1f6f50;
      --green-soft: #dff2e8;
      --blue: #225a8a;
      --blue-soft: #dcecf8;
      --shadow: 0 10px 30px rgba(60, 36, 12, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(143, 45, 34, 0.08), transparent 28%),
        radial-gradient(circle at top right, rgba(34, 90, 138, 0.08), transparent 24%),
        linear-gradient(180deg, #faf6ef 0%, var(--bg) 100%);
    }}
    .wrap {{
      width: min(1480px, calc(100vw - 40px));
      margin: 0 auto;
      padding: 28px 0 60px;
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(143,45,34,0.95), rgba(77,28,22,0.95));
      color: #fff9f5;
      border-radius: 24px;
      padding: 28px 30px;
      box-shadow: var(--shadow);
    }}
    .hero h1 {{
      margin: 0 0 10px;
      font-size: 34px;
      line-height: 1.1;
    }}
    .hero p {{
      margin: 0;
      line-height: 1.7;
      color: rgba(255,249,245,0.9);
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin: 22px 0 28px;
    }}
    .stat {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 18px 20px;
      box-shadow: var(--shadow);
    }}
    .stat-label {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }}
    .stat-value {{
      font-size: 30px;
      font-weight: 700;
      color: var(--brand);
    }}
    .section {{
      margin-top: 28px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 24px 26px;
      box-shadow: var(--shadow);
    }}
    .section h2 {{
      margin: 0 0 14px;
      font-size: 24px;
    }}
    .section p.lead {{
      margin: 0 0 18px;
      color: var(--muted);
      line-height: 1.75;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 700;
      margin-right: 6px;
      margin-bottom: 6px;
      border: 1px solid transparent;
    }}
    .badge-danger {{ background: var(--brand-soft); color: var(--brand); border-color: #edb5aa; }}
    .badge-warning {{ background: var(--gold-soft); color: var(--gold); border-color: #ebd399; }}
    .badge-success {{ background: var(--green-soft); color: var(--green); border-color: #b9e1ce; }}
    .badge-soft {{ background: var(--blue-soft); color: var(--blue); border-color: #bdd9ef; }}
    .badge-dark {{ background: #ece9e2; color: #4b5563; border-color: #d6d1c7; }}
    .badge-muted {{ background: #f3f1eb; color: #8a8f98; border-color: #e4e0d8; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 8px;
      overflow: hidden;
      border-radius: 16px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 12px 10px;
      text-align: left;
      vertical-align: top;
      font-size: 14px;
      line-height: 1.6;
    }}
    th {{
      color: var(--muted);
      font-weight: 700;
      background: #fbf8f1;
    }}
    .grid-2 {{
      display: grid;
      grid-template-columns: 1.05fr 0.95fr;
      gap: 22px;
    }}
    .case-list {{
      display: grid;
      gap: 18px;
    }}
    .case-card {{
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 16px;
      background: #fffdfa;
    }}
    .case-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
      margin-bottom: 10px;
    }}
    .case-title {{
      font-weight: 700;
      font-size: 16px;
    }}
    .module {{
      color: var(--muted);
      font-weight: 500;
    }}
    .case-note {{
      color: #4b5563;
      line-height: 1.7;
      margin-bottom: 14px;
    }}
    .case-grid {{
      display: grid;
      grid-template-columns: minmax(280px, 34%) 1fr;
      gap: 16px;
      align-items: start;
    }}
    .image-wrap {{
      background: #f8f5ee;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 10px;
      min-height: 180px;
    }}
    .image-wrap img {{
      width: 100%;
      display: block;
      border-radius: 12px;
    }}
    .empty-image {{
      color: var(--muted);
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .text-panels {{
      display: grid;
      gap: 12px;
    }}
    .panel {{
      border: 1px solid var(--line);
      border-radius: 16px;
      overflow: hidden;
      background: #fff;
    }}
    .panel-title {{
      background: #fbf8f1;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
    }}
    .text-block {{
      padding: 12px;
      white-space: pre-wrap;
      line-height: 1.75;
      font-size: 14px;
    }}
    .text-block.empty {{
      color: var(--muted);
    }}
    .mermaid-box {{
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 18px;
      padding: 14px;
      overflow: auto;
    }}
    .footnote {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.7;
      margin-top: 14px;
    }}
    @media (max-width: 1080px) {{
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
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
  mermaid.initialize({{
    startOnLoad: true,
    theme: 'base',
    themeVariables: {{
      primaryColor: '#f8dfd9',
      primaryTextColor: '#1f2937',
      primaryBorderColor: '#8f2d22',
      lineColor: '#8f2d22',
      secondaryColor: '#dcecf8',
      tertiaryColor: '#dff2e8',
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


def build_report_html(assessment: dict, run_summary: dict, run_map: dict[str, dict]) -> str:
    summary = Counter(assessment.get("summary", {}) or {})
    records = list(assessment.get("records", []) or [])
    confirmed = [item for item in records if item["content_error_status"] == "confirmed_transcription_error"]
    recheck = [item for item in records if item["content_error_status"] == "needs_manual_recheck"]
    excluded = [item for item in records if item["content_error_status"] == "source_issue_excluded"]
    clean = [item for item in records if item["content_error_status"] == "no_clear_content_error"]
    usage = run_summary.get("usage_totals", {}) or {}
    latency = run_summary.get("latency_summary", {}) or {}

    cards = "".join(build_case_card(item, run_map, "danger") for item in confirmed + excluded)

    body = f"""
<div class="wrap">
  <section class="hero">
    <h1>{REPORT_TITLE}</h1>
    <p>口径已经切到“只看转录内容有没有录错”。空格、换行、格式标签风格、展示包装差异，以及源题自身逻辑冲突，都不再直接算成模型内容错误。</p>
  </section>

  <section class="stats">
    <div class="stat"><div class="stat-label">总题量</div><div class="stat-value">{len(records)}</div></div>
    <div class="stat"><div class="stat-label">确认录错</div><div class="stat-value">{summary.get('confirmed_transcription_error', 0)}</div></div>
    <div class="stat"><div class="stat-label">当前无明确内容错误</div><div class="stat-value">{summary.get('no_clear_content_error', 0)}</div></div>
    <div class="stat"><div class="stat-label">待继续复核</div><div class="stat-value">{summary.get('needs_manual_recheck', 0)}</div></div>
    <div class="stat"><div class="stat-label">源题问题已排除</div><div class="stat-value">{summary.get('source_issue_excluded', 0)}</div></div>
    <div class="stat"><div class="stat-label">总 tokens</div><div class="stat-value">{format_int(usage.get('total_tokens'))}</div></div>
    <div class="stat"><div class="stat-label">平均耗时</div><div class="stat-value">{format_seconds(latency.get('avg_seconds'))}</div></div>
  </section>

  <section class="section">
    <h2>当前 skill 流转图</h2>
    <p class="lead">这张图描述的是现在仓库里这套 skill 的真实主链路。生产主干和评估审查层已经拆开了，局部精修支线保留但当前 200 题主跑批还没有接入。</p>
    <div class="mermaid-box">
      <pre class="mermaid">{escape(build_mermaid_flow())}</pre>
    </div>
    <div class="footnote">节点编号和说明见下表，方便你直接和 runtime、prompt、评估层一一对应。</div>
  </section>

  <section class="section">
    <h2>节点说明</h2>
    <table>
      <thead>
        <tr><th>编号</th><th>节点</th><th>当前作用</th></tr>
      </thead>
      <tbody>
        {build_node_rows()}
      </tbody>
    </table>
  </section>

  <section class="section">
    <h2>200题内容错误结论</h2>
    <p class="lead">这部分只统计“模型是否把文字、公式、字段内容录错”。不把纯格式差异和源题自身冲突算进模型错误率。</p>
    <div>
      {badge('confirmed_transcription_error', 'danger')}
      {badge('no_clear_content_error', 'success')}
      {badge('needs_manual_recheck', 'warning')}
      {badge('source_issue_excluded', 'soft')}
    </div>
    <div class="grid-2" style="margin-top:16px;">
      <div>
        <table>
          <thead>
            <tr><th>分类</th><th>数量</th><th>解释</th></tr>
          </thead>
          <tbody>
            <tr><td>确认录错</td><td>{summary.get('confirmed_transcription_error', 0)}</td><td>明确看到模型把题目文字、公式、字段内容录错。</td></tr>
            <tr><td>当前无明确内容错误</td><td>{summary.get('no_clear_content_error', 0)}</td><td>忽略格式差异后，当前没有看到明确内容错。</td></tr>
            <tr><td>待继续复核</td><td>{summary.get('needs_manual_recheck', 0)}</td><td>目前证据不足，不能直接判对或判错。</td></tr>
            <tr><td>源题问题排除</td><td>{summary.get('source_issue_excluded', 0)}</td><td>源图本身冲突或污染，不纳入模型错误率。</td></tr>
          </tbody>
        </table>
      </div>
      <div>
        <table>
          <thead>
            <tr><th>运行指标</th><th>值</th></tr>
          </thead>
          <tbody>
            <tr><td>模型</td><td>{escape(run_summary.get('model', '-'))}</td></tr>
            <tr><td>Prompt 版本</td><td>{escape(run_summary.get('prompt_version', '-'))}</td></tr>
            <tr><td>总题量</td><td>{format_int(run_summary.get('question_count'))}</td></tr>
            <tr><td>总 tokens</td><td>{format_int(usage.get('total_tokens'))}</td></tr>
            <tr><td>平均耗时</td><td>{format_seconds(latency.get('avg_seconds'))}</td></tr>
            <tr><td>最长耗时</td><td>{format_seconds(latency.get('max_seconds'))}</td></tr>
            <tr><td>最短耗时</td><td>{format_seconds(latency.get('min_seconds'))}</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>

  <section class="section">
    <h2>确认录错样本</h2>
    <p class="lead">下面这些卡片直接展示模型当前的题干、答案、解析文本，KaTeX 会把里面的公式渲染出来，便于你按字段审看。</p>
    <div class="case-list">
      {cards}
    </div>
  </section>

  <section class="section">
    <h2>模块分布</h2>
    <table>
      <thead>
        <tr>
          <th>模块</th>
          <th>确认录错</th>
          <th>当前无明确内容错误</th>
          <th>待继续复核</th>
          <th>源题排除</th>
        </tr>
      </thead>
      <tbody>
        {build_module_rows(records)}
      </tbody>
    </table>
  </section>

  <section class="section">
    <h2>待继续复核题号</h2>
    <p class="lead">这 39 题不是已经判错，而是现有证据还不够。你如果后面要继续缩窄错误率，这就是下一轮最应该打的池子。</p>
    <table>
      <thead>
        <tr><th>case_id</th><th>模块</th><th>原始 gate</th><th>当前复核原因</th></tr>
      </thead>
      <tbody>
        {build_recheck_rows(recheck)}
      </tbody>
    </table>
  </section>

  <section class="section">
    <h2>一句话结论</h2>
    <p class="lead">按“只看内容录错”的口径，这 200 题里当前已经确认的模型内容错误是 <strong>{summary.get('confirmed_transcription_error', 0)}</strong> 题；当前没有明确内容错误证据的是 <strong>{len(clean)}</strong> 题；另有 <strong>{len(recheck)}</strong> 题还需要继续人工缩圈，<strong>{len(excluded)}</strong> 题属于源题问题，已排除出模型错误统计。</p>
  </section>
</div>
"""
    return html_shell(body, REPORT_TITLE)


def build_flow_html() -> str:
    body = f"""
<div class="wrap">
  <section class="hero">
    <h1>当前 skill 流转图</h1>
    <p>这份单页只展示当前仓库里的 teacher-handout-visual-split-vision-primary 主链路，适合单独拿去讲 runtime 分层。</p>
  </section>

  <section class="section">
    <h2>Annotated Flow</h2>
    <div class="mermaid-box">
      <pre class="mermaid">{escape(build_mermaid_flow())}</pre>
    </div>
  </section>

  <section class="section">
    <h2>节点说明</h2>
    <table>
      <thead><tr><th>编号</th><th>节点</th><th>当前作用</th></tr></thead>
      <tbody>{build_node_rows()}</tbody>
    </table>
  </section>
</div>
"""
    return html_shell(body, "当前 skill 流转图")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build HTML report for 200-question content-error assessment.")
    parser.add_argument("--assessment-json", required=True)
    parser.add_argument("--run-json", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    assessment_path = Path(args.assessment_json).resolve()
    run_path = Path(args.run_json).resolve()
    out_dir = Path(args.out_dir).resolve()
    ensure_dir(out_dir)

    assessment = read_json(assessment_path)
    run_summary = read_json(run_path)
    run_records = list(run_summary.get("records", []) or [])
    run_map = {record.get("record_id", ""): record for record in run_records}

    report_path = out_dir / "content_error_200_report.html"
    flow_path = out_dir / "skill_flow_annotated.html"

    report_path.write_text(build_report_html(assessment, run_summary, run_map), encoding="utf-8")
    flow_path.write_text(build_flow_html(), encoding="utf-8")

    print(
        json.dumps(
            {
                "report_html": str(report_path),
                "flow_html": str(flow_path),
                "assessment_json": str(assessment_path),
                "run_json": str(run_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
