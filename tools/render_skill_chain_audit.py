from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = WORKSPACE_ROOT / "outputs" / "visual_transcription_v0.1" / "runtime_chain_audit_20260629"


STAGES = [
    {
        "id": "S0",
        "name": "题目切分输入",
        "kind": "upstream",
        "mode": "上游拆题 skill / 非本轮重点",
        "script": "teacher_pdf_visual_question_split_v02.py",
        "input": "PDF / 讲义页",
        "output": "question_image, stem_image, analysis_image, transcription_json",
        "does_vision": "是，上游视觉拆题",
        "notes": [
            "如果这里没有产出干净的 stem_image，后面题干图检测只能在整张 question_image 上找图。",
            "这一轮转录任务默认不回头修完整性，但漏出的 stem_image 质量会直接影响题干图识别。",
        ],
    },
    {
        "id": "S1",
        "name": "运行时编排",
        "kind": "orchestrator",
        "mode": "规则/脚本",
        "script": "teacher_pdf_visual_runtime_vision_primary.py",
        "input": "split 输出",
        "output": "prepare -> transcribe -> assetize 串联执行",
        "does_vision": "否",
        "notes": [
            "这里只负责调度，不做识图。",
            "当前链路会先跑 prepare_option_source，再跑转录，再跑 assetize。",
        ],
    },
    {
        "id": "S2",
        "name": "题目是否像选择题",
        "kind": "gate",
        "mode": "规则/脚本",
        "script": "option_choice_gating.py",
        "input": "question_uid + stem_text + OCR 片段 + 图片路径",
        "output": "gating_result",
        "does_vision": "否",
        "notes": [
            "这里只判断是否值得跑选项图片检测。",
            "它不负责题干图，不负责解析图，也不看图内真实语义。",
        ],
    },
    {
        "id": "S3",
        "name": "选项图检测",
        "kind": "detection",
        "mode": "视觉模型优先，失败则规则兜底",
        "script": "option_anchor_detection.detect_option_anchors",
        "input": "题目图 + gating_result",
        "output": "option_visual_blocks / unassigned_image_bboxes",
        "does_vision": "是，但只面向选项图",
        "notes": [
            "这是针对 A/B/C/D 选项配图的，不是题干图主通道。",
            "如果 gating 没放行，这一步可能根本不跑。",
        ],
    },
    {
        "id": "S4",
        "name": "题干图/解析图检测",
        "kind": "detection",
        "mode": "视觉模型优先，空结果再走启发式",
        "script": "option_anchor_detection.detect_public_figure_regions",
        "input": "stem_image 或 question_image；analysis_image",
        "output": "stem_image_bboxes / analysis_image_bboxes",
        "does_vision": "是，这才是题干图主通道",
        "notes": [
            "当前代码里如果没有 ARK_API_KEY，会直接 return 空结果，连启发式兜底都不会进。",
            "就算有 key，模型返回空框后，才会退到基于暗像素带的启发式框图。",
            "如果 stem_image 为空，只能在 question_image 这张长图里找图，难度会明显上升。",
        ],
    },
    {
        "id": "S5",
        "name": "资产计划生成",
        "kind": "mapping",
        "mode": "规则/脚本",
        "script": "option_crop_staging.build_staged_visual_assets",
        "input": "option blocks + stem/analysis bboxes",
        "output": "staged_visual_assets",
        "does_vision": "否",
        "notes": [
            "这里只把 bbox 映射成 after_stem / after_analysis / option_inline。",
            "如果上一环没框出来，这里不会再自己发现新图。",
        ],
    },
    {
        "id": "S6",
        "name": "主转录流水线",
        "kind": "transcription",
        "mode": "视觉模型 + 规则混合",
        "script": "visual_transcription_pipeline.py",
        "input": "prepared source json",
        "output": "visual_transcription_results.json",
        "does_vision": "是，但它负责文字/公式/字段，不负责重新找题干图",
        "notes": [
            "Layer 1 并发：visual_structure_node + raw_blocks_prompt_node。",
            "raw_blocks_model_node 才是真正的视觉转录调用。",
            "后面的 parse / normalize / quality_audit 都是在处理文本和结构，不会新增图片框。",
        ],
    },
    {
        "id": "S7",
        "name": "图片实体裁切",
        "kind": "materialize",
        "mode": "规则/脚本",
        "script": "assetize_question_images.materialize_staged_asset",
        "input": "staged_visual_assets + source images",
        "output": "question_assets/* + manifest + review html",
        "does_vision": "否",
        "notes": [
            "这里只按 bbox 直接裁图，不做二次识图。",
            "框歪了，裁出来就歪；框没来，这里就是 0 图。",
        ],
    },
    {
        "id": "S8",
        "name": "落库展示重排",
        "kind": "render",
        "mode": "规则/脚本",
        "script": "assetize_question_images.build_display_blocks",
        "input": "文本字段 + materialized assets",
        "output": "display_blocks / question_asset_review.html",
        "does_vision": "否",
        "notes": [
            "这里决定图片穿插到题干后、解析后、还是选项内。",
            "如果 display 看起来错位，可能是 placement_scope 问题，不一定是识图问题。",
        ],
    },
]


MISS_REASONS = [
    {
        "title": "上游没有干净 stem_image",
        "severity": "high",
        "details": "题干图检测会退化为在整张 question_image 上找图，图和文字粘连严重时容易漏。",
    },
    {
        "title": "没有 ARK_API_KEY 时题干图检测直接短路",
        "severity": "critical",
        "details": "detect_public_figure_regions 当前先判 key，没 key 直接返回空，不会进 public figure 启发式。",
    },
    {
        "title": "视觉模型没给框，才会落到启发式兜底",
        "severity": "high",
        "details": "启发式依赖暗像素带，对浅线条函数图、细几何线、文字密集区很弱。",
    },
    {
        "title": "staged_visual_assets 只消费已有框",
        "severity": "medium",
        "details": "一旦 detect_public_figure_regions 漏图，后续 assetize 不会再补救。",
    },
    {
        "title": "assetize 只裁切不识别",
        "severity": "medium",
        "details": "当前裁图阶段没有二次视觉校正，所有切坏图本质上都是前面 bbox 问题。",
    },
]


AUDIT_CHECKS = [
    "先看 source json 里该题有没有 stem_image / analysis_image；如果没有，后面漏图风险天然升高。",
    "再看 optionprep debug 里的 stem_image_bboxes / analysis_image_bboxes 是否为空。",
    "如果 bbox 为空，直接定位到 detect_public_figure_regions；不是 assetize 的锅。",
    "如果 bbox 有值但图切坏，定位到 bbox 本身质量或 materialize 直接裁切逻辑。",
    "如果图切对了但展示错位，定位到 build_display_blocks / placement_scope。",
]


def stage_color(kind: str) -> str:
    return {
        "upstream": "#eef2ff",
        "orchestrator": "#ecfeff",
        "gate": "#fef3c7",
        "detection": "#fee2e2",
        "mapping": "#dcfce7",
        "transcription": "#ede9fe",
        "materialize": "#e0f2fe",
        "render": "#f3e8ff",
    }.get(kind, "#f8fafc")


def severity_color(level: str) -> str:
    return {
        "critical": "#b42318",
        "high": "#c4320a",
        "medium": "#175cd3",
    }.get(level, "#475467")


def render_html() -> str:
    stage_cards = []
    for stage in STAGES:
        notes = "".join(f"<li>{item}</li>" for item in stage["notes"])
        stage_cards.append(
            f"""
            <section class="stage-card" style="background:{stage_color(stage['kind'])}">
              <div class="stage-head">
                <span class="stage-id">{stage['id']}</span>
                <h3>{stage['name']}</h3>
              </div>
              <div class="meta">
                <span class="pill">{stage['mode']}</span>
                <span class="pill dark">{stage['does_vision']}</span>
              </div>
              <p><strong>脚本：</strong><code>{stage['script']}</code></p>
              <p><strong>输入：</strong>{stage['input']}</p>
              <p><strong>输出：</strong>{stage['output']}</p>
              <ul>{notes}</ul>
            </section>
            """
        )

    reason_cards = []
    for reason in MISS_REASONS:
        reason_cards.append(
            f"""
            <div class="issue-card">
              <div class="issue-level" style="color:{severity_color(reason['severity'])}">{reason['severity']}</div>
              <h4>{reason['title']}</h4>
              <p>{reason['details']}</p>
            </div>
            """
        )

    audit_items = "".join(f"<li>{item}</li>" for item in AUDIT_CHECKS)
    now = datetime.now().isoformat(timespec="seconds")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>当前 Skill 链路审计</title>
  <style>
    body {{
      margin: 0;
      background: #f5f7fb;
      color: #182230;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    }}
    header {{
      padding: 28px 32px;
      background: linear-gradient(135deg, #0f172a, #1d4ed8);
      color: white;
    }}
    header h1 {{ margin: 0 0 8px; font-size: 28px; }}
    header p {{ margin: 0; opacity: .9; line-height: 1.7; }}
    main {{ padding: 24px; max-width: 1400px; margin: 0 auto; }}
    .section {{
      background: white;
      border: 1px solid #e4e7ec;
      border-radius: 18px;
      padding: 20px;
      margin-bottom: 20px;
      box-shadow: 0 10px 30px rgba(16, 24, 40, 0.06);
    }}
    .section h2 {{ margin: 0 0 12px; font-size: 22px; }}
    .section p {{ line-height: 1.75; }}
    .flow {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 14px;
    }}
    .stage-card {{
      border: 1px solid rgba(16, 24, 40, 0.08);
      border-radius: 16px;
      padding: 16px;
    }}
    .stage-head {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
    }}
    .stage-id {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      border-radius: 999px;
      background: rgba(15, 23, 42, 0.9);
      color: white;
      font-size: 13px;
      font-weight: 700;
    }}
    h3, h4 {{ margin: 0; }}
    .meta {{ margin: 10px 0 12px; }}
    .pill {{
      display: inline-block;
      margin: 0 8px 8px 0;
      padding: 4px 10px;
      border-radius: 999px;
      background: white;
      color: #175cd3;
      font-size: 12px;
      font-weight: 600;
    }}
    .pill.dark {{
      background: #111827;
      color: white;
    }}
    code {{
      background: rgba(255,255,255,0.7);
      padding: 2px 6px;
      border-radius: 6px;
      font-size: 12px;
    }}
    ul {{
      margin: 10px 0 0 18px;
      line-height: 1.7;
      padding: 0;
    }}
    .issues {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
    }}
    .issue-card {{
      border: 1px solid #e4e7ec;
      border-radius: 14px;
      padding: 16px;
      background: #fff;
    }}
    .issue-level {{
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      margin-bottom: 8px;
    }}
    .quicklist li {{ margin-bottom: 8px; }}
    .summary-grid {{
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 18px;
    }}
    @media (max-width: 960px) {{
      .summary-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>当前 Skill 链路审计</h1>
    <p>生成时间：{now}</p>
    <p>目标：把“题干图为什么漏、当前到底哪些环节是真视觉、哪些只是规则兜底”完整摊开，便于你逐环节审核。</p>
  </header>
  <main>
    <section class="section">
      <h2>一句话结论</h2>
      <p>现在这条链路里，真正负责“题干图识别”的核心只有 <code>detect_public_figure_regions</code> 这一段；后面的 staged assets、assetize、display 都只是在消费它给出的 bbox。也就是说，题干图没出来，绝大多数时候不是展示页没插图，而是前面根本没检测到图。</p>
    </section>

    <section class="section">
      <h2>链路全貌</h2>
      <div class="flow">
        {''.join(stage_cards)}
      </div>
    </section>

    <section class="section">
      <h2>为什么题干图会漏</h2>
      <div class="issues">
        {''.join(reason_cards)}
      </div>
    </section>

    <section class="section">
      <h2>你现在最该看的检查点</h2>
      <div class="summary-grid">
        <div>
          <ul class="quicklist">{audit_items}</ul>
        </div>
        <div>
          <p><strong>建议你重点盯的中间产物：</strong></p>
          <ul class="quicklist">
            <li><code>teacher_visual_question_transcription_optionprep_v1.1.json</code>：看题干图 bbox 有没有出来。</li>
            <li><code>teacher_visual_question_transcription_optionprep_v1.1.debug.json</code>：看 gating、detection、staged_visual_assets 是怎么走的。</li>
            <li><code>visual_transcription_results.json</code>：这里只看文字/公式，不要指望它补图。</li>
            <li><code>question_asset_manifest_v0.1.json</code>：看图片资产最终有没有 materialized。</li>
            <li><code>question_asset_review.html</code>：看最终展示插图位置和切图观感。</li>
          </ul>
        </div>
      </div>
    </section>
  </main>
</body>
</html>
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html_path = OUT_DIR / "current_skill_chain_audit.html"
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "html": str(html_path),
        "stage_count": len(STAGES),
        "issue_count": len(MISS_REASONS),
    }
    html_path.write_text(render_html(), encoding="utf-8")
    (OUT_DIR / "current_skill_chain_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
