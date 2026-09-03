from __future__ import annotations

import argparse
import html
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt


WORKSPACE = Path(__file__).resolve().parents[1]
MD = MarkdownIt("default", {"html": True}).enable("table")
BLANK_CHARS = {"_", "\uff3f", "\u2014", "\uff0d", "\u2500", "\u2501", "-"}

LABELS = {
    "title": "\u82f1\u8bed\u9605\u8bfb\u5b8c\u6574\u94fe\u8def\u5ba1\u6838\u5305",
    "source_page": "\u539f\u9875",
    "final_result": "\u6700\u7ec8\u7ed3\u679c",
    "stem": "\u9898\u5e72",
    "answer": "\u7b54\u6848",
    "analysis": "\u89e3\u6790",
    "translation": "\u7ffb\u8bd1/\u8865\u5145",
    "empty": "\uff08\u7a7a\uff09",
    "no_page": "\u65e0\u539f\u9875",
    "no_field": "\u65e0\u53ef\u5c55\u793a\u5b57\u6bb5",
    "ready": "\u53ef\u76f4\u63a5\u770b",
    "blocked": "\u5df2\u62e6\u622a",
    "review": "\u9700\u590d\u6838",
    "summary": "\u5de6\u4fa7\u539f\u9875\uff0c\u53f3\u4fa7\u6700\u7ec8\u7ed3\u679c\uff1b\u957f\u6750\u6599\u9650\u9ad8\uff0c\u89e3\u6790/\u7ffb\u8bd1\u53ef\u6298\u53e0",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def rel_to_workspace(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return WORKSPACE / path


def rel_url(from_dir: Path, target: Path) -> str:
    return Path(target).resolve().relative_to(from_dir.resolve()).as_posix()


def page_number_from_ref(ref: str) -> int | None:
    text = str(ref or "")
    marker = "_p"
    if marker not in text:
        return None
    tail = text.split(marker, 1)[1]
    digits: list[str] = []
    for char in tail:
        if char.isdigit():
            digits.append(char)
            continue
        break
    return int("".join(digits)) if digits else None


def family_from_ref(ref: str) -> str:
    text = str(ref or "").lower()
    if text.startswith("reading_") or "reading_argument" in text:
        return "reading"
    if text.startswith("grammar_") or "grammar_clauses" in text:
        return "grammar"
    if text.startswith("writing_") or "writing_invitation" in text:
        return "writing"
    return ""


def candidate_page_image_paths(family: str, page: int) -> list[Path]:
    if not family or page <= 0:
        return []
    page_name = f"page_{page:03d}.png"
    roots = [
        WORKSPACE
        / "outputs"
        / "english_text_first_pipeline_v02_spec_20260715"
        / "controlled_runs"
        / "source_page_images_3docs_20260724_full"
        / family,
        WORKSPACE
        / "outputs"
        / "english_text_first_pipeline_v02_spec_20260715"
        / "controlled_runs"
        / "node5b6b_pdf_visual_audit_20260724"
        / "page_images"
        / "page_images"
        / family,
    ]
    if family == "grammar":
        roots.append(
            WORKSPACE
            / "outputs"
            / "english_text_first_pipeline_v01_20260714"
            / "grammar_clauses_p001_p008_window4_live_v2"
            / "evidence"
            / "page_images"
        )
    return [root / page_name for root in roots if (root / page_name).exists()]


def source_ref_values(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        for item in value:
            refs.extend(source_ref_values(item))
    elif isinstance(value, dict):
        for item in value.values():
            refs.extend(source_ref_values(item))
    return refs


def blank_span(length: int) -> str:
    width = max(80, min(520, length * 9))
    return f'<span class="blank" style="min-width:{width}px"></span>'


def preserve_blank_runs(text: str) -> str:
    out: list[str] = []
    run = 0
    run_char = ""

    def flush_run() -> None:
        nonlocal run, run_char
        if not run:
            return
        out.append(blank_span(run) if run >= 3 else html.escape(run_char * run))
        run = 0
        run_char = ""

    for char in text:
        if char in BLANK_CHARS:
            if run and char != run_char:
                flush_run()
            run += 1
            run_char = char
            continue
        flush_run()
        out.append(char)
    flush_run()
    return "".join(out)


def pipe_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if "|" not in stripped:
        return None
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells = [cell.strip() for cell in stripped.split("|")]
    if len(cells) < 2:
        return None
    return cells


def is_markdown_separator_row(line: str) -> bool:
    cells = pipe_cells(line)
    if not cells:
        return False
    for cell in cells:
        compact = cell.replace(":", "").replace("-", "").strip()
        if compact:
            return False
        if "-" not in cell:
            return False
    return True


def table_separator_for(line: str) -> str:
    cells = pipe_cells(line) or ["", ""]
    return "| " + " | ".join("---" for _ in cells) + " |"


def normalize_pipe_tables(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        cells = pipe_cells(line)
        if not cells or is_markdown_separator_row(line):
            out.append(line)
            index += 1
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if pipe_cells(next_line) and not is_markdown_separator_row(next_line):
            out.append(line)
            out.append(table_separator_for(line))
            index += 1
            while index < len(lines):
                row = lines[index]
                if pipe_cells(row):
                    out.append(row)
                    index += 1
                    continue
                break
            continue
        out.append(line)
        index += 1
    return "\n".join(out)


def normalize_for_render(markdown: Any) -> str:
    text = normalize_pipe_tables(html.unescape(str(markdown or "")).replace("\xa0", " "))
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if is_markdown_separator_row(line):
            lines.append(line)
        elif stripped and set(stripped) <= BLANK_CHARS and len(stripped) >= 3:
            lines.append('<div class="write-line"></div>')
        else:
            lines.append(preserve_blank_runs(line))
    return "\n".join(lines).strip()


def md_html(markdown: Any) -> str:
    text = normalize_for_render(markdown)
    if not text:
        return f'<div class="empty">{LABELS["empty"]}</div>'
    try:
        return MD.render(text)
    except Exception:
        return "<pre>" + html.escape(text) + "</pre>"


def plain_len(value: Any) -> int:
    return len(html.unescape(str(value or "")).strip())


def field(title: str, value: Any, *, secondary: bool = False, folded: bool = False) -> str:
    if plain_len(value) == 0:
        return ""
    rendered = md_html(value)
    css = "rendered"
    if plain_len(value) > 1400:
        css += " scroll-field"
    if folded or (secondary and plain_len(value) > 650):
        return (
            f'<details class="field folded"><summary>{html.escape(title)}</summary>'
            f'<div class="{css}">{rendered}</div></details>'
        )
    return f'<section class="field"><h3>{html.escape(title)}</h3><div class="{css}">{rendered}</div></section>'


def pages_html(record: dict[str, Any], out_dir: Path, refined: dict[str, Any] | None = None) -> str:
    page_paths: list[str] = []
    for page in record.get("page_images") or []:
        path = page.get("path") if isinstance(page, dict) else str(page)
        if path:
            page_paths.append(path)
    display = (record.get("rendered_record") or {}).get("display_question") or {}
    for asset in display.get("surface_assets") or []:
        if not isinstance(asset, dict):
            continue
        if asset.get("kind") in {"source_page", "source_page_fallback"} and asset.get("path"):
            page_paths.append(str(asset["path"]))
    source_refs = source_ref_values((record.get("rendered_record") or {}).get("source_refs_used"))
    if refined:
        source_refs.extend(source_ref_values(refined.get("source_refs")))
        source_refs.extend(source_ref_values(refined.get("asset_refs")))
    seen_ref_pages: set[tuple[str, int]] = set()
    for ref in source_refs:
        page = page_number_from_ref(ref)
        family = family_from_ref(ref)
        if page is None or not family:
            continue
        key = (family, page)
        if key in seen_ref_pages:
            continue
        seen_ref_pages.add(key)
        for path in candidate_page_image_paths(family, page):
            page_paths.append(str(path))

    seen: set[str] = set()
    seen_page_names: set[str] = set()
    figs: list[str] = []
    for path_text in page_paths:
        source = rel_to_workspace(path_text)
        if not source.exists():
            continue
        key = str(source.resolve())
        page_key = source.name.lower()
        if key in seen or page_key in seen_page_names:
            continue
        seen.add(key)
        seen_page_names.add(page_key)
        dest = out_dir / "assets" / "pages" / source.name
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        url = rel_url(out_dir, dest)
        figs.append(
            f'<figure><a href="{html.escape(url)}" target="_blank">'
            f'<img src="{html.escape(url)}" loading="lazy"></a>'
            f'<figcaption>{html.escape(source.name)}</figcaption></figure>'
        )
    return "".join(figs) or f'<div class="empty">{LABELS["no_page"]}</div>'


def options_markdown(options: Any) -> str:
    if not isinstance(options, list):
        return ""
    lines: list[str] = []
    for opt in options:
        if not isinstance(opt, dict):
            continue
        label = str(opt.get("label") or "").strip()
        text = str(opt.get("text") or "").strip()
        if label or text:
            lines.append(f"{label}. {text}".strip())
    return "\n\n".join(lines)


def compact_text(value: Any) -> str:
    return "".join(str(value or "").split()).lower()


def split_display_chunks(value: Any) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for line in str(value or "").splitlines():
        if line.strip():
            current.append(line)
            continue
        if current:
            chunks.append("\n".join(current).strip())
            current = []
    if current:
        chunks.append("\n".join(current).strip())
    return chunks or ([str(value or "").strip()] if str(value or "").strip() else [])


FIELD_REF_KEYS = {
    "passage_markdown": ["passage_refs"],
    "stem_markdown": ["stem_refs"],
    "options_markdown": ["option_refs"],
    "support_markdown": ["context_refs", "example_refs", "rubric_refs"],
    "answer_markdown": ["answer_refs"],
    "analysis_markdown": ["analysis_refs"],
    "translation_markdown": ["translation_refs"],
}


def refs_for_display_field(refined: dict[str, Any], field_name: str) -> set[str]:
    refs = refined.get("source_refs") if isinstance(refined.get("source_refs"), dict) else {}
    out: set[str] = set()
    for ref_key in FIELD_REF_KEYS.get(field_name, []):
        value = refs.get(ref_key)
        if isinstance(value, list):
            out.update(str(item) for item in value if str(item).strip())
    return out


def dedupe_display_by_source_refs(display: dict[str, Any], refined: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(refined, dict):
        return display
    cleaned = dict(display)
    seen: list[tuple[set[str], str]] = []
    field_order = [
        "passage_markdown",
        "stem_markdown",
        "options_markdown",
        "support_markdown",
        "answer_markdown",
        "analysis_markdown",
        "translation_markdown",
    ]
    for field_name in field_order:
        refs = refs_for_display_field(refined, field_name)
        value = cleaned.get(field_name)
        if plain_len(value) == 0:
            continue
        kept_chunks: list[str] = []
        for chunk in split_display_chunks(value):
            compact = compact_text(chunk)
            if len(compact) < 16:
                kept_chunks.append(chunk)
                continue
            duplicate = False
            for seen_refs, seen_text in seen:
                if refs and seen_refs and refs.isdisjoint(seen_refs):
                    continue
                if compact and compact in seen_text:
                    duplicate = True
                    break
            if not duplicate:
                kept_chunks.append(chunk)
        cleaned[field_name] = "\n\n".join(kept_chunks).strip()
        field_compact = compact_text(cleaned.get(field_name))
        if refs and len(field_compact) >= 16:
            seen.append((refs, field_compact))
    return cleaned


def structured_display(
    record: dict[str, Any],
    refined_by_group: dict[str, dict[str, Any]] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    gid = str(record.get("source_group_id") or "")
    rendered_record = record.get("rendered_record") or {}
    rendered_display = rendered_record.get("display_question") or {}
    refined = (refined_by_group or {}).get(gid)
    if isinstance(refined, dict) and visual_heavy_record(rendered_record, rendered_display, refined):
        return dedupe_display_by_source_refs(compact_visual_heavy_display(gid, rendered_display, refined), refined), refined
    if isinstance(rendered_display, dict) and any(
        plain_len(rendered_display.get(key))
        for key in ["stem_markdown", "answer_markdown", "analysis_markdown", "translation_markdown"]
    ):
        return dedupe_display_by_source_refs(rendered_display, refined), refined
    if isinstance(refined, dict):
        sq = refined.get("standard_question")
        if isinstance(sq, dict):
            stem_parts = [str(sq.get("stem") or "").strip(), options_markdown(sq.get("options"))]
            source_surfaces = refined.get("source_surfaces") if isinstance(refined.get("source_surfaces"), dict) else {}
            visual_surface = source_surfaces.get("visual") if isinstance(source_surfaces.get("visual"), dict) else {}
            writing_surface = source_surfaces.get("writing_surface") if isinstance(source_surfaces.get("writing_surface"), dict) else {}
            display = {
                    "title": sq.get("title") or refined.get("source_packet_id") or gid,
                    "passage_markdown": sq.get("passage") or "",
                    "stem_markdown": str(sq.get("stem") or "").strip(),
                    "options_markdown": options_markdown(sq.get("options")),
                    "answer_markdown": sq.get("answer") or "",
                    "analysis_markdown": sq.get("analysis") or "",
                    "translation_markdown": sq.get("translation") or "",
                    "visual_surface_markdown": visual_surface.get("text") or "",
                    "writing_surface_markdown": writing_surface.get("text") or "",
                }
            return dedupe_display_by_source_refs(display, refined), refined
    return rendered_display, refined


def visual_heavy_record(rendered_record: dict[str, Any], display: dict[str, Any], refined: dict[str, Any]) -> bool:
    blocks = set(str(item) for item in (display.get("rendering_blocks") or []))
    plan = rendered_record.get("render_instruction_plan") or {}
    visual_sections = plan.get("visual_recovered_sections") or rendered_record.get("visual_recovered_sections") or []
    source_surfaces = refined.get("source_surfaces") if isinstance(refined.get("source_surfaces"), dict) else {}
    has_surface_text = any(
        isinstance(source_surfaces.get(key), dict) and plain_len(source_surfaces[key].get("text"))
        for key in ["visual", "writing_surface"]
    )
    question = refined.get("standard_question") or {}
    has_long_context = plain_len(question.get("context")) > 220
    stem_overexpanded = (
        plain_len(display.get("stem_markdown")) > plain_len(question.get("stem")) + 360
        and bool(blocks & {"parent_context", "support_context", "visual_surface", "writing_surface", "material_card"})
    )
    support_context_should_be_separated = (
        plain_len(question.get("context")) > 0
        and not bool(blocks & {"visual_surface", "writing_surface", "markdown_table"})
    )
    return bool(
        visual_sections
        or has_surface_text
        or has_long_context
        or "markdown_table" in blocks
        or "material_card" in blocks
        or stem_overexpanded
        or support_context_should_be_separated
    )


def compact_visual_heavy_display(gid: str, rendered_display: dict[str, Any], refined: dict[str, Any]) -> dict[str, Any]:
    question = refined.get("standard_question") if isinstance(refined.get("standard_question"), dict) else {}
    options_text = options_markdown(question.get("options"))
    blocks = set(str(item) for item in (rendered_display.get("rendering_blocks") or []))
    source_surfaces = refined.get("source_surfaces") if isinstance(refined.get("source_surfaces"), dict) else {}
    visual_surface = source_surfaces.get("visual") if isinstance(source_surfaces.get("visual"), dict) else {}
    writing_surface = source_surfaces.get("writing_surface") if isinstance(source_surfaces.get("writing_surface"), dict) else {}
    context = str(question.get("context") or "").strip()
    examples = str(question.get("examples") or "").strip()
    context_belongs_to_visual = bool(
        blocks & {"visual_surface", "writing_surface", "markdown_table"}
    ) or plain_len(visual_surface.get("text")) > 0
    visual_text_actual = [
        context if context_belongs_to_visual else "",
        str(visual_surface.get("text") or "").strip(),
    ]
    visual_text_parts = []
    if any(visual_text_actual):
        visual_text_parts.append("以左侧原页为准；下方仅保留机器可读的知识结构/视觉转录备份。")
        visual_text_parts.extend(visual_text_actual)
    support_text_parts = [
        context if not context_belongs_to_visual else "",
        examples,
    ]
    writing_text_parts = [str(writing_surface.get("text") or "").strip()]
    stem_text = str(question.get("stem") or "").strip()
    if not stem_text:
        stem_text = str(rendered_display.get("stem_markdown") or "").strip()
    compact = dict(rendered_display)
    compact.update(
        {
            "title": question.get("title") or refined.get("source_packet_id") or gid,
            "passage_markdown": question.get("passage") or "",
            "stem_markdown": stem_text,
            "options_markdown": options_text,
            "answer_markdown": question.get("answer") or "",
            "analysis_markdown": question.get("analysis") or "",
            "translation_markdown": question.get("translation") or "",
            "support_markdown": "\n\n".join(part for part in support_text_parts if part).strip(),
            "visual_surface_markdown": "\n\n".join(part for part in visual_text_parts if part).strip(),
            "writing_surface_markdown": "\n\n".join(part for part in writing_text_parts if part).strip(),
        }
    )
    return compact


def surface_assets_html(display: dict[str, Any], out_dir: Path) -> str:
    assets = display.get("surface_assets") if isinstance(display.get("surface_assets"), list) else []
    cards: list[str] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        kind = str(asset.get("kind") or "")
        if kind in {"source_page", "source_page_fallback"}:
            continue
        if kind == "missing_surface_asset":
            continue
        path_text = str(asset.get("path") or "")
        if not path_text:
            continue
        source = rel_to_workspace(path_text)
        if not source.exists():
            continue
        dest = out_dir / "assets" / "surfaces" / source.name
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        url = rel_url(out_dir, dest)
        caption = str(asset.get("caption") or source.name)
        cards.append(
            f'<figure class="surface-card"><a href="{html.escape(url)}" target="_blank">'
            f'<img src="{html.escape(url)}" loading="lazy"></a>'
            f'<figcaption>{html.escape(caption)}</figcaption></figure>'
        )
    if not cards:
        return ""
    return '<section class="field"><h3>视觉/作答区资产</h3><div class="surface-grid">' + "".join(cards) + "</div></section>"


def record_html(
    record: dict[str, Any],
    index: int,
    out_dir: Path,
    refined_by_group: dict[str, dict[str, Any]] | None = None,
    question_structure_mode: bool = False,
) -> str:
    rendered_record = record.get("rendered_record") or {}
    if question_structure_mode:
        display, refined = structured_display(record, refined_by_group)
    else:
        display = rendered_record.get("display_question") or {}
        refined = None
    admission = rendered_record.get("admission_profile") or record.get("admission_profile") or {}
    status = str(record.get("render_status") or rendered_record.get("render_status") or "")
    mode = str(admission.get("admission_mode") or "")
    title = str(display.get("title") or record.get("source_group_id") or "")
    if status == "READY":
        status_label = LABELS["ready"]
    elif status == "BLOCKED":
        status_label = LABELS["blocked"]
    else:
        status_label = LABELS["review"]
    meta = " / ".join(x for x in [status_label, mode] if x)
    passage_label = "\u5171\u4eab\u6587\u7ae0/\u6750\u6599"
    options_note = ""
    fields = "\n".join(
        [
            field(passage_label, display.get("passage_markdown"), folded=True),
            field(LABELS["stem"], display.get("stem_markdown")),
            field("选项", display.get("options_markdown")),
            field("参考词汇/题干补充", display.get("support_markdown"), secondary=True),
            field(LABELS["answer"], display.get("answer_markdown")),
            field(LABELS["analysis"], display.get("analysis_markdown"), secondary=True),
            field(LABELS["translation"], display.get("translation_markdown"), secondary=True),
            field("表格/图示/视觉内容", display.get("visual_surface_markdown"), secondary=True, folded=True),
            field("作答区/作文纸", display.get("writing_surface_markdown"), secondary=True, folded=True),
            surface_assets_html(display, out_dir),
        ]
    )
    return f"""
<article class="case" id="{html.escape(str(record.get('source_group_id') or index))}">
  <header class="case-head">
    <div><span class="idx">#{index}</span> <strong>{html.escape(str(record.get('source_group_id') or ''))}</strong> <span class="packet">{html.escape(title)}</span>{options_note}</div>
  </header>
  <div class="grid">
    <section class="source-col">
      <h2>{LABELS["source_page"]}</h2>
      <div class="pages">{pages_html(record, out_dir, refined)}</div>
    </section>
    <section class="result-col">
      <h2>{LABELS["final_result"]}</h2>
      {fields or f'<div class="empty">{LABELS["no_field"]}</div>'}
    </section>
  </div>
</article>
"""


def render(
    records: list[dict[str, Any]],
    out_dir: Path,
    title: str,
    refined_by_group: dict[str, dict[str, Any]] | None = None,
    question_structure_mode: bool = False,
) -> str:
    nav = "".join(
        f'<a href="#{html.escape(str(r.get("source_group_id") or i))}">{i}. {html.escape(str(r.get("source_group_id") or ""))}</a>'
        for i, r in enumerate(records, 1)
    )
    cases = "\n".join(
        record_html(record, idx, out_dir, refined_by_group, question_structure_mode)
        for idx, record in enumerate(records, 1)
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body {{ margin:0; background:#f6f8fb; color:#111827; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif; }}
.top {{ position:sticky; top:0; z-index:10; background:#fff; border-bottom:1px solid #d7dee8; padding:12px 20px; }}
h1 {{ margin:0 0 6px; font-size:22px; }}
.summary {{ color:#4b5563; font-size:14px; }}
.nav {{ display:flex; gap:8px; overflow:auto; padding-top:8px; }}
.nav a {{ flex:0 0 auto; color:#2563eb; text-decoration:none; border:1px solid #dbeafe; border-radius:999px; padding:3px 8px; font-size:13px; background:#eff6ff; }}
.case {{ margin:16px auto; max-width:1740px; background:#fff; border:1px solid #d7dee8; border-radius:8px; overflow:hidden; }}
.case-head {{ display:flex; align-items:center; justify-content:space-between; gap:16px; padding:10px 14px; background:#f9fafb; border-bottom:1px solid #d7dee8; }}
.idx {{ color:#64748b; margin-right:6px; }}
.packet {{ color:#64748b; font-size:13px; margin-left:8px; }}
.badge {{ border:1px solid #cbd5e1; border-radius:999px; padding:4px 10px; font-size:13px; color:#334155; background:#fff; white-space:nowrap; }}
.badge.ready {{ color:#047857; border-color:#a7f3d0; background:#ecfdf5; }}
.badge.blocked {{ color:#b91c1c; border-color:#fecaca; background:#fef2f2; }}
.grid {{ display:grid; grid-template-columns:minmax(360px, 0.82fr) minmax(560px, 1.18fr); gap:16px; padding:14px; align-items:start; }}
h2 {{ margin:0 0 8px; font-size:17px; }}
h3, summary {{ margin:12px 0 8px; font-size:17px; color:#0f172a; font-weight:700; }}
.pages {{ display:flex; flex-direction:row; gap:10px; overflow-x:auto; padding-bottom:8px; }}
figure {{ margin:0; flex:0 0 auto; }}
figure img {{ max-height:520px; width:auto; max-width:420px; border:1px solid #cbd5e1; background:white; }}
figcaption {{ color:#64748b; font-size:13px; margin-top:4px; }}
.field, .folded {{ border-top:1px solid #e5e7eb; padding-top:4px; }}
.field:first-child {{ border-top:0; }}
.rendered {{ font-size:17px; line-height:1.6; overflow-wrap:anywhere; }}
.scroll-field {{ max-height:430px; overflow:auto; border:1px solid #e5e7eb; border-radius:6px; padding:10px; background:#fff; }}
.rendered table {{ border-collapse:collapse; width:100%; margin:8px 0; font-size:15px; }}
.rendered th,.rendered td {{ border:1px solid #cbd5e1; padding:7px 9px; vertical-align:top; }}
.rendered th {{ background:#f1f5f9; font-weight:700; }}
.rendered p {{ margin:0 0 9px; }}
.rendered ol,.rendered ul {{ padding-left:1.35em; }}
.rendered u {{ text-decoration-thickness:2px; text-underline-offset:3px; }}
.blank {{ display:inline-block; border-bottom:2px solid #111827; height:0.9em; vertical-align:baseline; margin:0 3px; }}
.write-line {{ border-bottom:2px solid #111827; height:1.4em; margin:10px 0; }}
.surface-grid {{ display:flex; gap:12px; flex-wrap:wrap; align-items:flex-start; }}
.surface-card {{ margin:0; max-width:520px; }}
.surface-card img {{ width:500px; max-width:100%; border:1px solid #cbd5e1; background:white; }}
.surface-missing {{ margin-top:8px; color:#92400e; }}
.surface-missing pre {{ white-space:pre-wrap; background:#fffbeb; border:1px solid #fde68a; border-radius:6px; padding:8px; }}
.empty {{ color:#94a3b8; border:1px dashed #cbd5e1; padding:12px; border-radius:6px; }}
@media (max-width: 980px) {{ .grid {{ grid-template-columns:1fr; }} figure img {{ max-width:88vw; }} .rendered {{ font-size:16px; }} }}
</style>
</head>
<body>
<div class="top"><h1>{html.escape(title)}</h1><div class="summary">records={len(records)} | {LABELS["summary"]}</div><div class="nav">{nav}</div></div>
{cases}
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records-json", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--title", default=LABELS["title"])
    parser.add_argument("--output-name", default="index.html")
    parser.add_argument("--refined-packets-json")
    parser.add_argument("--question-structure-mode", action="store_true")
    parser.add_argument("--backup-existing", action="store_true")
    args = parser.parse_args()

    records_json = rel_to_workspace(args.records_json)
    out_dir = rel_to_workspace(args.out_dir)
    payload = read_json(records_json)
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise SystemExit("records-json does not contain a records list")
    refined_by_group: dict[str, dict[str, Any]] | None = None
    if args.refined_packets_json:
        refined_payload = read_json(rel_to_workspace(args.refined_packets_json))
        refined_packets = refined_payload.get("refined_packets") if isinstance(refined_payload, dict) else refined_payload
        if not isinstance(refined_packets, list):
            raise SystemExit("refined-packets-json does not contain a refined_packets list")
        refined_by_group = {
            str(packet.get("source_group_id") or ""): packet
            for packet in refined_packets
            if isinstance(packet, dict) and packet.get("source_group_id")
        }
    out_path = out_dir / args.output_name
    if args.backup_existing and out_path.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(out_path, out_path.with_name(f"{out_path.stem}.backup_{stamp}{out_path.suffix}"))
    write_text(
        out_path,
        render(
            records,
            out_dir,
            args.title,
            refined_by_group=refined_by_group,
            question_structure_mode=args.question_structure_mode,
        ),
    )
    print(json.dumps({"html": str(out_path), "record_count": len(records)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
