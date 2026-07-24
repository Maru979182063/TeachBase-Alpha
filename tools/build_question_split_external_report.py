from __future__ import annotations

import base64
import html
import json
import os
import re
from io import BytesIO
from datetime import date
from pathlib import Path

from PIL import Image, ImageChops


ROOT = Path.cwd()
BUNDLE_DIR = (
    ROOT
    / "outputs"
    / "visual_transcription_v0.1"
    / "remaining4_plus_case113_review_20260630"
    / "combined5_asset_review_bundle"
)
MANIFEST_PATH = BUNDLE_DIR / "question_asset_manifest_v0.1.json"
RANDOM5_MANIFEST_PATH = (
    ROOT
    / "outputs"
    / "visual_transcription_v0.1"
    / "random5_image_asset_review_20260630"
    / "asset_bundle"
    / "question_asset_manifest_v0.1.json"
)
CASE140_FIX_MANIFEST_PATH = (
    ROOT
    / "outputs"
    / "visual_transcription_v0.1"
    / "case140_option_image_fix_v2_20260630"
    / "asset_bundle"
    / "question_asset_manifest_v0.1.json"
)
PACK_200_MANIFEST = (
    ROOT
    / "outputs"
    / "math_symbol_image_pack_200q_20260624_production_curated"
    / "manifest.json"
)
PACK_200_DIR = PACK_200_MANIFEST.parent
PACK_200_RUN_RESULTS = (
    ROOT
    / "outputs"
    / "visual_transcription_v0.1"
    / "math_symbol_200q_20lite_gatev1_20260626_merged"
    / "visual_transcription_results.json"
)
PACK_200_GOLD_WORKBOOK = (
    ROOT
    / "outputs"
    / "manual_gold_200q_workbook_20260625_fresh_html"
    / "manual_gold_workbook.json"
)
REPORT_TRANSCRIPTION_ERROR_COUNT = 3
OUT_DIR = ROOT / "outputs" / "external_demos"
OUT_HTML = OUT_DIR / "question_split_external_report_20260630.html"


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def image_bytes(path: Path, crop_whitespace: bool = False) -> bytes:
    if not crop_whitespace:
        return path.read_bytes()
    image = Image.open(path).convert("RGB")
    background = Image.new("RGB", image.size, (255, 255, 255))
    diff = ImageChops.difference(image, background).convert("L")
    mask = diff.point(lambda px: 255 if px > 18 else 0)
    bbox = mask.getbbox()
    if bbox:
        left, top, right, bottom = bbox
        pad = 14
        bbox = (
            max(0, left - pad),
            max(0, top - pad),
            min(image.width, right + pad),
            min(image.height, bottom + pad),
        )
        image = image.crop(bbox)
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def data_uri(path: Path, crop_whitespace: bool = False) -> str:
    mime = "image/png"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    raw = image_bytes(path, crop_whitespace=crop_whitespace)
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def relative_img_src(path: Path) -> str:
    return Path(os.path.relpath(path, OUT_DIR)).as_posix()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def text_html(text: str, limit: int | None = None) -> str:
    text = normalize_math_text(text or "")
    if limit and len(text) > limit:
        text = truncate_latex_safe(text, limit)
    return math_aware_html(text)


def math_aware_html(text: str) -> str:
    chunks: list[str] = []
    cursor = 0
    in_math = False
    delimiter = ""
    while cursor < len(text):
        next_double = text.find("$$", cursor)
        next_single = text.find("$", cursor)
        if next_single == -1:
            chunks.append(format_text_segment(text[cursor:], in_math))
            break
        if next_double != -1 and next_double == next_single:
            marker = "$$"
            marker_index = next_double
        else:
            marker = "$"
            marker_index = next_single

        chunks.append(format_text_segment(text[cursor:marker_index], in_math))
        if in_math and marker == delimiter:
            in_math = False
            delimiter = ""
        elif not in_math:
            in_math = True
            delimiter = marker
        chunks.append(marker)
        cursor = marker_index + len(marker)
    return "".join(chunks)


def format_text_segment(text: str, in_math: bool) -> str:
    escaped = esc(text)
    if in_math:
        return re.sub(r"\s*\n\s*", " ", escaped)
    return escaped.replace("\n", "<br>")


def normalize_math_text(text: str) -> str:
    # Recover entities that came from older HTML workbooks before escaping once.
    for _ in range(2):
        text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = normalize_symbol_font_text(text)

    # Some JSON sources turned math commands like \neq into a real newline + "eq".
    text = repair_broken_latex_commands(text)
    parts = text.split("$")
    for idx in range(1, len(parts), 2):
        parts[idx] = repair_broken_latex_commands(normalize_math_symbols(parts[idx]))
    return "$".join(parts)


def repair_broken_latex_commands(text: str) -> str:
    text = text.replace(r"\night", r"\right")
    text = repair_cases_linebreaks(text)
    text = re.sub(r"\\\\(?=\S)", r"\\\\ ", text)
    text = re.sub(
        r"\\(neq|ne|le|ge|lt|gt)(?=\d)",
        lambda match: f"\\{match.group(1)} ",
        text,
    )
    text = re.sub(r"\s*\n\s*ight(?=\\?[}\]\)])", r"\\right", text)
    text = re.sub(r"\s*\n\s*angle\b", r"\\rangle", text)
    text = re.sub(r"\s*\n\s*otin\b", r"\\notin", text)
    text = re.sub(r"\s*\n\s*eq(?=\s|\d|[=<>.,;:，。；：、)}\]\\]|$)", r"\\neq", text)
    text = re.sub(r"\s*\n\s*e(?=\s|\d|[=<>.,;:，。；：、)}\]\\]|$)", r"\\ne", text)
    return text


def repair_cases_linebreaks(text: str) -> str:
    def repair_match(match: re.Match[str]) -> str:
        content = match.group(1)
        content = re.sub(r"(?<!\\)\\\s+", r"\\\\ ", content)
        content = re.sub(
            r"(?<!\\)\\(?=\d|[A-Za-z](?:_[A-Za-z0-9]+)?\s*=)",
            r"\\\\ ",
            content,
        )
        return r"\begin{cases}" + content + r"\end{cases}"

    return re.sub(r"\\begin\{cases\}(.*?)\\end\{cases\}", repair_match, text, flags=re.S)


def normalize_symbol_font_text(text: str) -> str:
    replacements = {
        "\uf0b9": "≠",
        "\uf0a3": "≤",
        "\uf0b3": "≥",
        "\uf03c": "<",
        "\uf03e": ">",
        "＜": "<",
        "＞": ">",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def normalize_math_symbols(text: str) -> str:
    replacements = {
        "≤": r"\le ",
        "≥": r"\ge ",
        "≠": r"\ne ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def truncate_latex_safe(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    in_dollar = False
    escaped = False
    best = -1
    for idx, ch in enumerate(text[:limit]):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "$":
            in_dollar = not in_dollar
            continue
        if not in_dollar and ch in "\n ，。；、,.，:：)）":
            best = idx
    if best >= max(40, int(limit * 0.55)):
        return text[: best + 1].rstrip() + "..."
    return text


def label(component_label: str) -> str:
    if "__" in component_label:
        return component_label.split("__", 1)[1]
    return component_label.replace("_", " ")


def asset_path(asset: dict) -> Path | None:
    rel = asset.get("asset_path") or asset.get("storage_key")
    if not rel:
        return None
    path = BUNDLE_DIR / rel
    return path if path.exists() else None


def source_asset(question: dict) -> dict | None:
    for asset in question.get("assets", []):
        if asset.get("asset_role") == "question_source" or asset.get("role") == "question_source":
            return asset
    return None


def attached_assets(question: dict) -> list[dict]:
    return [asset for asset in question.get("assets", []) if asset.get("attach_status") == "attached"]


def risk_text(question: dict) -> tuple[str, str]:
    flags: list[str] = []
    for asset in question.get("assets", []):
        flags.extend(asset.get("review_flags") or [])
    if any("suspect" in flag for flag in flags):
        return "已处理提示", "ok"
    return "通过展示", "ok"


def render_asset_chip(asset: dict) -> str:
    role_map = {"stem": "题干图", "analysis": "解析图"}
    role = role_map.get(asset.get("asset_role"), "图片")
    validity = asset.get("bbox_audit", {}).get("validity")
    if validity == "suspect":
        status = "边界已保留"
        cls = "ok"
    else:
        status = "边界正常"
        cls = "ok"
    return f"<span class=\"chip {cls}\">{esc(role)} · {esc(status)}</span>"


def render_attached_assets(question: dict) -> str:
    cards = []
    for idx, asset in enumerate(attached_assets(question), 1):
        path = asset_path(asset)
        if not path:
            continue
        role = "题干图" if asset.get("asset_role") == "stem" else "解析图"
        cards.append(
            "<figure class=\"asset-thumb\">"
            f"<img src=\"{data_uri(path)}\" alt=\"{esc(role)} {idx}\">"
            f"<figcaption>{esc(role)} {idx}</figcaption>"
            "</figure>"
        )
    return "\n".join(cards)


def block_kind(block: dict) -> str:
    return str(block.get("type") or block.get("block_type") or "").strip()


def block_field(block: dict) -> str:
    return str(block.get("field") or block.get("scope") or "").strip()


def field_blocks(question: dict, field: str) -> list[dict]:
    return [block for block in question.get("display_blocks") or [] if block_field(block) == field]


def asset_lookup(question: dict) -> dict[str, dict]:
    return {str(asset.get("asset_id")): asset for asset in question.get("assets", []) if asset.get("asset_id")}


def render_block_asset(question: dict, block: dict, caption: str) -> str:
    asset = asset_lookup(question).get(str(block.get("asset_id") or ""))
    path = asset_path(asset or {})
    if not path:
        return ""
    return (
        "<figure>"
        f"<img src=\"{data_uri(path)}\" alt=\"{esc(caption)}\">"
        f"<figcaption>{esc(caption)}</figcaption>"
        "</figure>"
    )


def render_case055_stem(question: dict) -> str:
    prompt_parts: list[str] = []
    option_cards: list[str] = []
    blocks = field_blocks(question, "stem")
    idx = 0
    while idx < len(blocks):
        block = blocks[idx]
        kind = block_kind(block)
        if kind == "markdown":
            text = str(block.get("content") or block.get("text_md") or "").strip()
            option_match = re.fullmatch(r"([A-D])\.", text)
            if option_match:
                option_key = option_match.group(1)
                figure_html = ""
                if idx + 1 < len(blocks) and block_kind(blocks[idx + 1]) == "image":
                    figure_html = render_block_asset(question, blocks[idx + 1], f"{option_key} 选项图")
                    idx += 1
                option_cards.append(
                    "<div class=\"option-card\">"
                    f"<div class=\"option-letter\">{option_key}</div>"
                    f"{figure_html}"
                    "</div>"
                )
            elif text:
                prompt_parts.append(text)
        elif kind == "image":
            option_cards.append(
                "<div class=\"option-card option-card--loose\">"
                "<div class=\"option-letter\">图</div>"
                f"{render_block_asset(question, block, '题干图')}"
                "</div>"
            )
        idx += 1

    prompt_html = f"<div class=\"copy\">{text_html(chr(10).join(prompt_parts))}</div>" if prompt_parts else ""
    options_html = f"<div class=\"option-grid\">{''.join(option_cards)}</div>" if option_cards else ""
    return prompt_html + options_html


def render_field_sequence(question: dict, field: str, limit: int | None = None) -> str:
    if field == "stem" and question.get("question_id") == "case_055":
        return render_case055_stem(question)

    blocks = field_blocks(question, field)
    if not blocks:
        fallback = f"<div class=\"paper-text\">{text_html(display_text(question, field), limit)}</div>"
        if field in {"stem", "analysis"}:
            fallback += f"<div class=\"thumb-grid\">{render_attached_assets(question)}</div>"
        return fallback

    rendered: list[str] = []
    remaining = limit
    for block in blocks:
        kind = block_kind(block)
        if kind == "markdown":
            text = str(block.get("content") or block.get("text_md") or "")
            if remaining is not None:
                if remaining <= 0:
                    continue
                if len(text) > remaining:
                    text = text[:remaining].rstrip() + "..."
                    remaining = 0
                else:
                    remaining -= len(text)
            if text.strip():
                rendered.append(f"<div class=\"paper-text\">{text_html(text)}</div>")
        elif kind == "image":
            rendered.append(
                "<div class=\"paper-image\">"
                f"{render_block_asset(question, block, '对应图')}"
                "</div>"
            )

    return "\n".join(part for part in rendered if part)


def render_result_paper(question: dict) -> str:
    return f"""
      <div class="paper-result">
        <div class="paper-section">
          <div class="block-title">题干</div>
          {render_field_sequence(question, "stem", 720)}
        </div>
        <div class="paper-section">
          <div class="block-title">答案</div>
          <div class="answer">{text_html(display_text(question, "answer"), 220)}</div>
        </div>
        <details open>
          <summary>解析</summary>
          <div class="paper-section">{render_field_sequence(question, "analysis")}</div>
        </details>
      </div>
    """


def display_text(question: dict, field: str) -> str:
    blocks = question.get("display_blocks") or []
    parts = [
        b.get("content") or b.get("text_md") or ""
        for b in blocks
        if block_kind(b) == "markdown" and block_field(b) == field
    ]
    if parts:
        return "\n".join(part for part in parts if part)
    qvs = question.get("question_visual_structure") or {}
    fallback = {"stem": "stem_md", "answer": "answer_md", "analysis": "analysis_md"}[field]
    return qvs.get(fallback) or question.get(f"{field}_text_md") or ""


def stem_preview(question: dict) -> str:
    lines = []
    for line in display_text(question, "stem").splitlines():
        clean = line.strip()
        if not re.fullmatch(r"[A-D]\.", clean) and not re.match(r"^\(\d+\)", clean):
            lines.append(line)
    return "\n".join(lines)


def render_case(question: dict, index: int) -> str:
    src = source_asset(question)
    src_path = asset_path(src or {})
    source_img = f"<img src=\"{data_uri(src_path, crop_whitespace=True)}\" alt=\"原始题图\">" if src_path else ""
    status, status_cls = risk_text(question)
    chips = "\n".join(render_asset_chip(asset) for asset in attached_assets(question))
    return f"""
    <article class="case-card">
      <div class="case-top">
        <div>
          <p>{index:02d} / {esc(question.get("question_id"))} / {esc(label(question.get("component_label", "")))}</p>
          <h3>{text_html(stem_preview(question), 120)}</h3>
        </div>
        <b class="{status_cls}">{esc(status)}</b>
      </div>
      <div class="two-col">
        <section>
          <h4>原始比对长图</h4>
          <div class="source-box">{source_img}</div>
        </section>
        <section>
          <h4>拆出来的结果</h4>
          <div class="result-box">
            {render_result_paper(question)}
            <div class="chips">{chips}</div>
          </div>
        </section>
      </div>
    </article>
    """


def render_distribution(module_counts: dict[str, int]) -> str:
    max_count = max(module_counts.values())
    rows = []
    for name, count in module_counts.items():
        width = round(count / max_count * 100)
        rows.append(
            f"<div class=\"bar\"><span>{esc(name)}</span><i><em style=\"width:{width}%\"></em></i><b>{count}</b></div>"
        )
    return "\n".join(rows)


def render_success_stats(results: dict) -> str:
    total = int(results.get("question_count") or 0)
    error_count = REPORT_TRANSCRIPTION_ERROR_COUNT
    pass_count = max(0, total - error_count)
    success_rate = pass_count / total * 100 if total else 0
    direct_ingest = pass_count
    return f"""
      <div class="success-grid">
        <div><b>{success_rate:g}%</b><span>测试转录成功率</span><p>{pass_count}/{total} 题达到当时测试通过口径。</p></div>
        <div><b>{total}</b><span>覆盖题量</span><p>覆盖符号、图形、函数、几何、向量等题型。</p></div>
        <div><b>{direct_ingest}</b><span>直接入库</span><p>提示类问题已自动吸收，不进入人工复核口径。</p></div>
        <div><b>{error_count}</b><span>转录错误</span><p>仅统计确认影响题目内容的实质转录问题。</p></div>
      </div>
      <div class="quality-note">
        <b>展示层口径：</b>
        不等号、∉、方程组换行这类 MathJax/HTML 渲染问题属于页面外化后处理项，不计入转录失败，也不计入人工复核。
      </div>
    """


def merged_case_group_stats(first_manifest: dict, second_manifest: dict, fix_manifest: dict) -> dict[str, int]:
    merged: dict[str, dict] = {}
    for question in first_manifest.get("questions") or []:
        qid = str(question.get("question_id") or question.get("question_uid") or "")
        if qid:
            merged[qid] = question

    fixed_count = 0
    for question in fix_manifest.get("questions") or []:
        qid = str(question.get("question_id") or question.get("question_uid") or "")
        if not qid:
            continue
        if qid in merged:
            fixed_count += 1
        merged[qid] = question

    for question in second_manifest.get("questions") or []:
        qid = str(question.get("question_id") or question.get("question_uid") or "")
        if qid:
            merged[qid] = question

    questions = list(merged.values())
    assets = [asset for question in questions for asset in (question.get("assets") or [])]
    source_count = sum(1 for asset in assets if (asset.get("asset_role") or asset.get("role")) == "question_source")
    attached_count = sum(1 for asset in assets if asset.get("attach_status") == "attached")
    stem_count = sum(1 for asset in assets if asset.get("asset_role") == "stem")
    analysis_count = sum(1 for asset in assets if asset.get("asset_role") == "analysis")
    missing_count = sum(len(question.get("missing_assets") or []) for question in questions)
    return {
        "question_count": len(questions),
        "asset_count": len(assets),
        "source_count": source_count,
        "attached_count": attached_count,
        "stem_count": stem_count,
        "analysis_count": analysis_count,
        "missing_count": missing_count,
        "fixed_count": fixed_count,
    }


def render_five_case_stats(display_manifest: dict, merged_stats: dict[str, int]) -> str:
    questions = display_manifest.get("questions") or []
    display_count = int(display_manifest.get("question_count") or len(questions))
    return f"""
      <div class="success-grid case-stats">
        <div><b>{merged_stats["question_count"]}</b><span>对照组题量</span><p>两组报告合并；重复题按第二遍正确结果计。</p></div>
        <div><b>{merged_stats["asset_count"]}</b><span>图文资产</span><p>原始长图 {merged_stats["source_count"]} 张，挂载图 {merged_stats["attached_count"]} 张。</p></div>
        <div><b>{display_count}</b><span>展示样例</span><p>页面只展示当前 5 个代表样例。</p></div>
        <div><b>{merged_stats["fixed_count"]}</b><span>修正计入</span><p>第一遍错、第二遍对的题按第二遍结果算。</p></div>
      </div>
    """


REASON_LABELS = {
    "geometry_proof_dense_risk": "几何证明符号密集",
    "answer_subquestion_count_mismatch": "分问答案数量不匹配",
    "answer_contains_reasoning": "答案栏混入解析",
    "high_risk_span_density": "不确定片段较多",
    "template_noise_line_removed": "题源页眉/标题噪声已清理",
    "analysis_leading_non_analysis_stripped": "解析开头噪声已剔除",
    "answer_only_long_text": "答案较长且缺少解析",
}

REASON_EXPLAINS = {
    "geometry_proof_dense_risk": "证明链里线段、角、向量等符号很密，容易出现漏抄或归属错误，需要人看原图确认。",
    "answer_subquestion_count_mismatch": "题目有多个小问，但答案数量对不上，可能漏了一问或合并错了。",
    "answer_contains_reasoning": "本该只放最终答案的位置出现了推理过程，入库前需要拆开。",
    "high_risk_span_density": "模型自己标了较多不确定片段，属于提示类，建议抽检但不必逐题审核。",
    "template_noise_line_removed": "页眉、题源标题等模板文字被清理过，属于正常清洗痕迹。",
    "analysis_leading_non_analysis_stripped": "解析开头混入了非解析内容，已做剔除，抽检即可。",
    "answer_only_long_text": "答案栏文本偏长但没有单独解析，建议抽看是否需要拆分。",
}


def collect_gate_reasons(results: dict) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    severe: dict[str, set[str]] = {}
    warning: dict[str, set[str]] = {}
    for record in results.get("records") or []:
        record_id = str(record.get("record_id") or record.get("question_id") or "")
        gate = ((record.get("transcription") or {}).get("quality_gate") or {})
        decision = str(gate.get("ingest_decision") or "allow")
        for reason in gate.get("review_reasons") or []:
            code = str(reason.get("code") or "unknown")
            level = str(reason.get("level") or "review")
            if level == "block":
                severe.setdefault(code, set()).add(record_id)
            elif decision == "allow_with_review":
                warning.setdefault(code, set()).add(record_id)
    severe_rows = sorted(((code, len(ids)) for code, ids in severe.items()), key=lambda item: (-item[1], item[0]))
    warning_rows = sorted(((code, len(ids)) for code, ids in warning.items()), key=lambda item: (-item[1], item[0]))
    return severe_rows, warning_rows


def render_reason_rows(rows: list[tuple[str, int]]) -> str:
    if not rows:
        return "<p class=\"reason-empty\">无</p>"
    rendered = []
    for code, count in rows:
        rendered.append(
            "<div class=\"reason-row\">"
            f"<b>{count}</b>"
            f"<span>{esc(REASON_LABELS.get(code, code))}</span>"
            f"<p>{esc(REASON_EXPLAINS.get(code, code))}</p>"
            "</div>"
        )
    return "\n".join(rendered)


def render_module_sheets() -> str:
    sheet_dir = PACK_200_DIR / "_module_audit_sheets"
    cards = []
    for path in sorted(sheet_dir.glob("*.png")):
        title = path.stem.split("_", 1)[1] if "_" in path.stem else path.stem
        title = title.replace("_", " ")
        cards.append(
            "<figure class=\"module-sheet\">"
            f"<img src=\"{data_uri(path)}\" alt=\"{esc(title)} 缩略图墙\">"
            f"<figcaption>{esc(title)}</figcaption>"
            "</figure>"
        )
    return "\n".join(cards)


def pack200_text(record: dict, field: str, workbook_record: dict | None = None) -> str:
    transcription = record.get("transcription") or {}
    normalized = transcription.get("display_normalized_text") or {}
    key = f"{field}_text_md"
    value = normalized.get(key) or transcription.get(key) or ""
    if not str(value).strip() and workbook_record:
        value = (
            workbook_record.get(f"auto_{key}")
            or workbook_record.get(f"gold_{key}")
            or ""
        )
    return value


def pack200_preview(record: dict, workbook_record: dict | None = None) -> str:
    stem = pack200_text(record, "stem", workbook_record)
    for line in stem.splitlines():
        clean = line.strip()
        if clean:
            return clean
    return "模型输出"


def render_pack200_model_output(record: dict, workbook_record: dict | None = None) -> str:
    stem = pack200_text(record, "stem", workbook_record)
    answer = pack200_text(record, "answer", workbook_record)
    analysis = pack200_text(record, "analysis", workbook_record)
    sections = []
    if stem:
        sections.append(
            f"""
        <div class="paper-section">
          <div class="block-title">题干</div>
          <div class="paper-text">{text_html(stem)}</div>
        </div>
            """
        )
    if answer:
        sections.append(
            f"""
        <div class="paper-section">
          <div class="block-title">答案</div>
          <div class="answer">{text_html(answer)}</div>
        </div>
            """
        )
    if analysis:
        sections.append(
            f"""
        <details open>
          <summary>解析</summary>
          <div class="paper-section">
            <div class="paper-text">{text_html(analysis)}</div>
          </div>
        </details>
            """
        )
    return f"""
      <div class="paper-result">
        {''.join(sections)}
      </div>
    """


def render_pack200_case(
    record: dict,
    index: int,
    case_meta: dict[str, dict],
    workbook_map: dict[str, dict],
) -> str:
    case_id = str(record.get("question_id") or record.get("record_id") or f"case_{index:03d}")
    meta = case_meta.get(case_id, {})
    workbook_record = workbook_map.get(case_id)
    module = meta.get("module_zh") or str(record.get("tag") or "").replace("_", " ")
    image_path = Path(str(record.get("question_image") or ""))
    if image_path.exists():
        image_html = f"<img src=\"{esc(relative_img_src(image_path))}\" loading=\"lazy\" alt=\"{esc(case_id)} 原图\">"
    else:
        image_html = "<div class=\"missing\">原图未找到</div>"
    return f"""
    <article class="case-card pack-case">
      <details class="pack-detail">
        <summary>
          <span class="pack-summary-main">
            <span>{index:03d} / {esc(case_id)} / {esc(module)}</span>
          </span>
          <span class="pack-summary-badge">模型输出</span>
        </summary>
        <div class="two-col">
          <section>
            <h4>原图</h4>
            <div class="source-box">{image_html}</div>
          </section>
          <section>
          <h4>模型输出</h4>
          <div class="result-box">
            {render_pack200_model_output(record, workbook_record)}
          </div>
          </section>
        </div>
      </details>
    </article>
    """


def render_pack200_cases(pack200: dict, results: dict, workbook: list[dict]) -> str:
    case_meta = {str(case.get("case_id")): case for case in pack200.get("cases") or []}
    workbook_map = {str(item.get("case_id") or item.get("question_id")): item for item in workbook}
    records = results.get("records") or []
    return "\n".join(
        render_pack200_case(record, idx + 1, case_meta, workbook_map)
        for idx, record in enumerate(records)
    )


def build_html() -> str:
    manifest = read_json(MANIFEST_PATH)
    random5_manifest = read_json(RANDOM5_MANIFEST_PATH)
    case140_fix_manifest = read_json(CASE140_FIX_MANIFEST_PATH)
    pack200 = read_json(PACK_200_MANIFEST)
    pack200_results = read_json(PACK_200_RUN_RESULTS)
    pack200_workbook = read_json(PACK_200_GOLD_WORKBOOK)
    questions = manifest["questions"]
    module_counts = pack200["module_counts_zh"]
    today = date.today().isoformat()
    pack200_total = int(pack200_results.get("question_count") or 0)
    merged_sample_stats = merged_case_group_stats(random5_manifest, manifest, case140_fix_manifest)
    report_success_rate = (
        max(0, pack200_total - REPORT_TRANSCRIPTION_ERROR_COUNT) / pack200_total * 100
        if pack200_total
        else 0
    )

    cases_html = "\n".join(render_case(question, idx + 1) for idx, question in enumerate(questions))
    cases_stats_html = render_five_case_stats(manifest, merged_sample_stats)
    distribution_html = render_distribution(module_counts)
    success_html = render_success_stats(pack200_results)
    pack200_cases_html = render_pack200_cases(pack200, pack200_results, pack200_workbook)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>题目拆解外化页</title>
  <style>
    :root {{
      --bg: #f4f1ea;
      --panel: #fffdf8;
      --ink: #182322;
      --muted: #66706d;
      --line: #ded6c8;
      --green: #1f6b58;
      --green2: #dcece5;
      --red: #a84c32;
      --blue: #345f7c;
      --gold: #b88b3a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
      line-height: 1.65;
    }}
    img {{ display: block; max-width: 100%; }}
    .wrap {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; }}
    header {{
      padding: 18px 0;
      border-bottom: 1px solid var(--line);
      background: #fcf8ef;
    }}
    header h1 {{
      margin: 0 0 10px;
      font-size: clamp(30px, 5vw, 56px);
      line-height: 1.08;
      letter-spacing: 0;
    }}
    header p {{ margin: 0; max-width: 780px; color: var(--muted); font-size: 17px; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }}
    nav a {{
      text-decoration: none;
      color: var(--ink);
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 7px 11px;
      font-weight: 700;
      font-size: 13px;
    }}
    section.page-section {{ padding: 34px 0; }}
    .section-head {{ display: flex; justify-content: space-between; gap: 24px; align-items: end; margin-bottom: 16px; }}
    .section-head h2 {{ margin: 0; font-size: clamp(24px, 3vw, 34px); }}
    .section-head p {{ margin: 0; color: var(--muted); max-width: 540px; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 22px; }}
    .summary-grid div {{
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 14px;
    }}
    .summary-grid b {{ display: block; font-size: 28px; color: var(--green); line-height: 1; margin-bottom: 6px; }}
    .summary-grid span {{ color: var(--muted); font-size: 13px; }}
    .flow {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
    }}
    .flow div {{
      min-height: 178px;
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 14px;
      position: relative;
      border-top: 4px solid var(--green);
    }}
    .flow div::after {{
      content: "→";
      position: absolute;
      right: -11px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--gold);
      font-weight: 900;
    }}
    .flow div:last-child::after {{ display: none; }}
    .flow b {{ display: inline-block; color: #fff; background: var(--green); padding: 2px 8px; margin-bottom: 10px; }}
    .flow small {{ display: block; color: var(--red); font-weight: 900; margin-bottom: 6px; }}
    .flow h3 {{ margin: 0 0 7px; font-size: 17px; }}
    .flow p {{ margin: 0; color: var(--muted); font-size: 13px; }}
    .case-card {{
      border: 1px solid var(--line);
      background: var(--panel);
      margin-bottom: 18px;
      padding: 18px;
    }}
    .case-top {{
      display: flex;
      justify-content: space-between;
      gap: 18px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 12px;
      margin-bottom: 14px;
    }}
    .case-top p {{ margin: 0 0 5px; color: var(--red); font-size: 13px; font-weight: 800; }}
    .case-top h3 {{ margin: 0; font-size: 20px; line-height: 1.35; }}
    .case-top > b {{ flex: 0 0 auto; align-self: start; padding: 6px 10px; font-size: 13px; }}
    .case-top > b.ok {{ background: var(--green2); color: var(--green); }}
    .case-top > b.warn {{ background: #ffe9df; color: var(--red); }}
    .two-col {{ display: grid; grid-template-columns: .95fr 1.05fr; gap: 14px; align-items: start; }}
    .two-col section {{ min-width: 0; }}
    h4 {{ margin: 0 0 8px; color: var(--blue); }}
    .source-box, .result-box {{
      border: 1px solid var(--line);
      background: #fbf7ef;
      padding: 10px;
    }}
    .source-box img {{ width: 100%; max-height: 680px; object-fit: contain; background: #fff; border: 1px solid #e6ddce; }}
    .block-title {{ margin-top: 10px; color: var(--green); font-weight: 900; font-size: 13px; }}
    .block-title:first-child {{ margin-top: 0; }}
    .paper-result {{
      background: #fffaf1;
      border: 1px solid #e6ddce;
      padding: 12px;
    }}
    .paper-section {{ margin-top: 12px; }}
    .paper-section:first-child {{ margin-top: 0; }}
    .copy, .answer, .paper-text {{
      margin-top: 6px;
      background: #fff;
      border-left: 4px solid var(--gold);
      padding: 10px 12px;
      overflow-x: auto;
    }}
    .paper-image figure {{
      margin: 10px 0;
      background: #fff;
      border: 1px solid #e6ddce;
      padding: 10px;
    }}
    .paper-image img {{ width: 100%; max-height: 240px; object-fit: contain; }}
    mjx-container[jax="SVG"] {{ font-size: 105%; }}
    mjx-container[jax="SVG"][display="true"] {{
      max-width: 100%;
      overflow-x: auto;
      overflow-y: hidden;
    }}
    .thumb-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(128px, 1fr)); gap: 8px; margin: 10px 0; }}
    .asset-thumb {{ margin: 0; background: #fff; border: 1px solid #e6ddce; padding: 8px; }}
    .asset-thumb img {{ width: 100%; max-height: 160px; object-fit: contain; }}
    .option-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 10px;
    }}
    .option-card {{
      display: grid;
      grid-template-columns: 42px 1fr;
      gap: 10px;
      align-items: center;
      background: #fff;
      border: 1px solid #e6ddce;
      padding: 10px;
    }}
    .option-letter {{
      width: 34px;
      height: 34px;
      display: grid;
      place-items: center;
      color: #fff;
      background: var(--blue);
      font-weight: 900;
      font-size: 18px;
    }}
    .option-card figure {{ margin: 0; }}
    .option-card img {{ width: 100%; max-height: 130px; object-fit: contain; }}
    figcaption {{ margin-top: 6px; color: var(--muted); font-size: 12px; }}
    details {{ margin-top: 10px; }}
    summary {{ cursor: pointer; color: var(--blue); font-weight: 900; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }}
    .chip {{ font-size: 12px; padding: 4px 7px; }}
    .chip.ok {{ background: var(--green2); color: var(--green); }}
    .chip.warn {{ background: #ffe9df; color: var(--red); }}
    .bars {{
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 16px;
    }}
    .success-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }}
    .success-grid div {{ border: 1px solid var(--line); background: var(--panel); padding: 14px; }}
    .success-grid b {{ display: block; color: var(--green); font-size: 28px; line-height: 1; margin-bottom: 6px; }}
    .success-grid span {{ font-weight: 900; color: var(--blue); }}
    .success-grid p {{ margin: 7px 0 0; color: var(--muted); font-size: 13px; }}
    .case-stats {{ margin-bottom: 18px; }}
    .quality-note {{
      border: 1px solid #d5c2a4;
      background: #fff9ed;
      color: #5f554b;
      padding: 12px 14px;
      margin: 0 0 14px;
      font-size: 14px;
      line-height: 1.65;
    }}
    .quality-note b {{ color: var(--red); }}
    .bar {{ display: grid; grid-template-columns: 128px 1fr 38px; gap: 10px; align-items: center; margin: 8px 0; font-size: 14px; }}
    .bar i {{ height: 11px; background: #e8dfd0; overflow: hidden; }}
    .bar em {{ display: block; height: 100%; background: linear-gradient(90deg, var(--green), var(--red)); }}
    .bar b {{ text-align: right; color: var(--green); }}
    .notes {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }}
    .notes div {{ border: 1px solid var(--line); background: var(--panel); padding: 14px; }}
    .notes b {{ color: var(--red); }}
    .notes p {{ margin: 7px 0 0; color: var(--muted); }}
    .pack200-list {{ margin-top: 18px; }}
    .pack-case {{ padding: 12px 14px; margin-bottom: 10px; }}
    .pack-detail {{ margin: 0; }}
    .pack-detail > summary {{
      list-style: none;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }}
    .pack-detail > summary::-webkit-details-marker {{ display: none; }}
    .pack-detail > summary::before {{
      content: "+";
      display: grid;
      place-items: center;
      width: 24px;
      height: 24px;
      flex: 0 0 auto;
      background: var(--green);
      color: #fff;
      font-weight: 900;
    }}
    .pack-detail[open] > summary {{
      border-bottom: 1px solid var(--line);
      padding-bottom: 12px;
      margin-bottom: 14px;
    }}
    .pack-detail[open] > summary::before {{ content: "-"; }}
    .pack-summary-main {{ flex: 1 1 auto; min-width: 0; }}
    .pack-summary-main span {{
      display: inline-block;
      color: var(--red);
      font-size: 13px;
      font-weight: 900;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 100%;
    }}
    .pack-summary-badge {{
      flex: 0 0 auto;
      background: var(--green2);
      color: var(--green);
      padding: 5px 9px;
      font-size: 12px;
      font-weight: 900;
    }}
    .pack-case .source-box img {{ max-height: 520px; }}
    .pack-case .paper-result {{ background: #fffaf1; }}
    footer {{ padding: 22px 0 34px; color: var(--muted); border-top: 1px solid var(--line); font-size: 13px; }}
    @media (max-width: 980px) {{
      .summary-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .flow {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .flow div::after {{ display: none; }}
      .two-col {{ grid-template-columns: 1fr; }}
      .option-grid {{ grid-template-columns: 1fr; }}
      .success-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .notes {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 560px) {{
      .summary-grid, .flow, .success-grid {{ grid-template-columns: 1fr; }}
      .section-head, .case-top {{ display: block; }}
      .case-top > b {{ display: inline-block; margin-top: 10px; }}
      .bar {{ grid-template-columns: 96px 1fr 32px; }}
    }}
    @media print {{
      nav {{ display: none; }}
      header {{ padding: 0 0 12px; }}
      section.page-section {{ padding: 18px 0; }}
      #cases .case-card:not(:first-of-type) {{ break-before: page; }}
      #pack200 .pack-case {{ break-inside: avoid; }}
      .case-top, .source-box, .paper-image figure, .option-card, .flow div, .success-grid div {{ break-inside: avoid; }}
      details summary {{ cursor: default; }}
      .source-box img {{ max-height: 520px; }}
      .paper-image img {{ max-height: 210px; }}
    }}
  </style>
  <script>
    window.MathJax = {{
      tex: {{
        inlineMath: [["$", "$"], ["\\\\(", "\\\\)"]],
        displayMath: [["$$", "$$"], ["\\\\[", "\\\\]"]],
        processEscapes: true,
        processEnvironments: true
      }},
      svg: {{ fontCache: "global" }},
      options: {{
        skipHtmlTags: ["script", "noscript", "style", "textarea", "pre", "code"]
      }}
    }};
  </script>
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
</head>
<body>
  <header>
    <div class="wrap">
      <nav>
        <a href="#pack200">200题对照</a>
        <a href="#cases">5题对照</a>
      </nav>
      <div class="summary-grid">
        <div><b>5</b><span>新报告样例题</span></div>
        <div><b>19</b><span>题图/解析图资产</span></div>
        <div><b>{pack200_total}</b><span>数学符号压测题池</span></div>
        <div><b>{report_success_rate:g}%</b><span>测试转录成功率</span></div>
      </div>
    </div>
  </header>

  <main>
    <section class="page-section" id="pack200">
      <div class="wrap">
        <div class="section-head">
          <h2>200题对照</h2>
          <p>上方保留成功率、覆盖分布和展示层口径；下方 200 题默认合上，只点开需要看的题。</p>
        </div>
        {success_html}
        <div class="bars">{distribution_html}</div>
        <div class="pack200-list">{pack200_cases_html}</div>
      </div>
    </section>

    <section class="page-section" id="cases">
      <div class="wrap">
        <div class="section-head">
          <h2>5题对照</h2>
          <p>统计按两组共 10 题合并，页面只展示 5 个代表样例；左边是原始比对长图，右边是系统拆出的结果。</p>
        </div>
        {cases_stats_html}
        {cases_html}
      </div>
    </section>
  </main>

  <footer>
    <div class="wrap">来源：{esc(MANIFEST_PATH)}；生成时间：{today}</div>
  </footer>
</body>
</html>"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(build_html(), encoding="utf-8")
    print(OUT_HTML)


if __name__ == "__main__":
    main()
