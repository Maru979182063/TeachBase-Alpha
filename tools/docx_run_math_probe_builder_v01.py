from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


FIELDS = ["stem", "subquestions", "answer", "explanation", "teaching_note", "other_evidence"]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def block_index(block_stream: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(block.get("block_id")): block for block in block_stream.get("blocks") or []}


def patch_field(field: dict[str, Any], blocks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out = json.loads(json.dumps(field, ensure_ascii=False))
    markdowns: list[str] = []
    block_markdowns: list[dict[str, str]] = []
    for block_id in out.get("block_ids") or []:
        block = blocks.get(str(block_id))
        if not block:
            continue
        markdown = str(block.get("display_markdown") or block.get("text") or "").strip()
        if markdown:
            markdowns.append(markdown)
            block_markdowns.append({"block_id": str(block_id), "markdown": markdown})
    out["markdown"] = "\n\n".join(markdowns)
    out["block_markdowns"] = block_markdowns
    return out


def patch_draft_payload(
    payload: dict[str, Any],
    normalized_block_stream: dict[str, Any],
    group_id: str,
    normalized_block_stream_path: Path,
) -> dict[str, Any]:
    blocks = block_index(normalized_block_stream)
    out = json.loads(json.dumps(payload, ensure_ascii=False))
    draft_items = []
    for draft in out.get("draft_items") or []:
        if str(draft.get("source_group_id") or "") != group_id:
            continue
        for field_name in FIELDS:
            field = (draft.get("fields") or {}).get(field_name)
            if isinstance(field, dict):
                draft["fields"][field_name] = patch_field(field, blocks)
        draft_items.append(draft)
    out["draft_items"] = draft_items
    out["summary"] = {
        **(out.get("summary") or {}),
        "draft_count": len(draft_items),
        "probe_group_id": group_id,
        "run_math_normalized": True,
    }
    out["source_artifacts"] = {
        **(out.get("source_artifacts") or {}),
        "normalized_block_stream": str(normalized_block_stream_path),
    }
    return out


def render_simple_markdown(text: str, asset_root: Path | None = None) -> str:
    escaped = html.escape(text)
    return escaped.replace("\n", "<br>\n")


def render_probe(payload: dict[str, Any], out_path: Path) -> None:
    cards = []
    for draft in payload.get("draft_items") or []:
        fields_html = []
        for field in FIELDS:
            value = str(((draft.get("fields") or {}).get(field) or {}).get("markdown") or "").strip()
            if value:
                fields_html.append(f"<h3>{html.escape(field)}</h3><div class='md'>{render_simple_markdown(value)}</div>")
        cards.append(
            "<article>"
            f"<h2>{html.escape(str(draft.get('source_group_id') or draft.get('draft_id') or ''))}</h2>"
            + "".join(fields_html)
            + "</article>"
        )
    doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Run Math Probe Draft</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f5f7fb;color:#0f172a}}
article{{background:white;border:1px solid #ccd6e3;border-radius:8px;padding:18px;margin:18px 0}}
.md{{white-space:normal;font-size:18px;line-height:1.65}}
h3{{border-top:1px solid #e2e8f0;padding-top:12px}}
</style></head><body>
<h1>Run Math Probe Draft</h1>
{''.join(cards)}
</body></html>"""
    write_text(out_path, doc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Patch a source-backed draft payload with a normalized block stream for a single group probe.")
    parser.add_argument("--draft-payload", required=True, type=Path)
    parser.add_argument("--normalized-block-stream", required=True, type=Path)
    parser.add_argument("--group-id", required=True)
    parser.add_argument("--output-root", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = read_json(args.draft_payload)
    normalized = read_json(args.normalized_block_stream)
    patched = patch_draft_payload(payload, normalized, args.group_id, args.normalized_block_stream)
    doc_id = str(patched.get("doc_id") or "doc")
    out_json = args.output_root / doc_id / "source_backed_draft" / "docx_math_source_backed_draft_items.json"
    write_json(out_json, patched)
    render_probe(patched, args.output_root / doc_id / "source_backed_draft" / "run_math_probe.html")
    write_json(args.output_root / "payload_alias.json", patched)
    print(json.dumps({"output": str(out_json), "draft_count": len(patched.get("draft_items") or [])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
