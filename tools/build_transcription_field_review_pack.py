from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_pack_cases(pack_manifest_path: Path) -> dict[str, dict]:
    pack_dir = pack_manifest_path.parent
    cases: dict[str, dict] = {}
    if pack_manifest_path.suffix.lower() == ".csv":
        with pack_manifest_path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for case in reader:
                case_id = str(case.get("case_id", "")).strip()
                if not case_id:
                    continue
                case_copy = dict(case)
                rel_image = str(case.get("packaged_image", "")).strip()
                case_copy["absolute_image_path"] = str((pack_dir / rel_image).resolve()) if rel_image else ""
                cases[case_id] = case_copy
        return cases

    payload = read_json(pack_manifest_path)
    for case in payload.get("cases", []):
        case_id = str(case.get("case_id", "")).strip()
        if not case_id:
            continue
        case_copy = dict(case)
        rel_image = str(case.get("packaged_image", "")).strip()
        case_copy["absolute_image_path"] = str((pack_dir / rel_image).resolve()) if rel_image else ""
        cases[case_id] = case_copy
    return cases


def normalize_formula_spans(value: object) -> str:
    if not value:
        return ""
    return json.dumps(value, ensure_ascii=False)


def load_records(run_dir: Path) -> list[dict]:
    candidate_paths = [
        run_dir / "visual_transcription_results.json",
        run_dir / "visual_transcription_results.recovered.json",
    ]
    for result_path in candidate_paths:
        if result_path.exists():
            payload = read_json(result_path)
            return payload.get("records", []) if isinstance(payload, dict) else []
    return []


def record_to_row(record: dict, case: dict) -> dict:
    transcription = record.get("transcription") or {}
    return {
        "case_id": record.get("record_id", ""),
        "question_id": record.get("question_id", ""),
        "module_en": case.get("module_en", ""),
        "module_zh": case.get("module_zh", ""),
        "submodule_en": case.get("submodule_en", ""),
        "submodule_zh": case.get("submodule_zh", ""),
        "tags_en": case.get("tags_en", ""),
        "tags_zh": case.get("tags_zh", ""),
        "image_path": case.get("absolute_image_path", ""),
        "status": record.get("status", ""),
        "latency_seconds": record.get("latency_seconds", ""),
        "usage_total_tokens": (record.get("usage") or {}).get("total_tokens", ""),
        "usage_prompt_tokens": (record.get("usage") or {}).get("prompt_tokens", ""),
        "usage_completion_tokens": (record.get("usage") or {}).get("completion_tokens", ""),
        "stem_text_md": transcription.get("stem_text_md", ""),
        "answer_text_md": transcription.get("answer_text_md", ""),
        "analysis_text_md": transcription.get("analysis_text_md", ""),
        "question_image": transcription.get("question_image", "") or record.get("question_image", ""),
        "analysis_image": transcription.get("analysis_image", "") or record.get("analysis_image", ""),
        "stem_requires_image": transcription.get("stem_requires_image", ""),
        "analysis_requires_image": transcription.get("analysis_requires_image", ""),
        "uncertain_spans": normalize_formula_spans(transcription.get("uncertain_spans", [])),
        "formula_spans": normalize_formula_spans(transcription.get("formula_spans", [])),
        "error": record.get("error", ""),
    }


def write_csv(rows: list[dict], out_path: Path) -> None:
    headers = [
        "case_id",
        "question_id",
        "module_en",
        "module_zh",
        "submodule_en",
        "submodule_zh",
        "tags_en",
        "tags_zh",
        "image_path",
        "status",
        "latency_seconds",
        "usage_total_tokens",
        "usage_prompt_tokens",
        "usage_completion_tokens",
        "stem_text_md",
        "answer_text_md",
        "analysis_text_md",
        "question_image",
        "analysis_image",
        "stem_requires_image",
        "analysis_requires_image",
        "uncertain_spans",
        "formula_spans",
        "error",
    ]
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def build_html(rows: list[dict], out_path: Path) -> None:
    cards: list[str] = []
    for row in rows:
        image_rel = ""
        image_path = str(row.get("image_path", "") or "")
        if image_path:
            try:
                image_rel = Path(image_path).relative_to(out_path.parent).as_posix()
            except ValueError:
                image_rel = Path(image_path).as_posix()
        cards.append(
            """
<section class="card">
  <div class="card-head">
    <div>
      <div class="case-id">{case_id}</div>
      <div class="module">{module_zh} / {submodule_zh}</div>
    </div>
    <div class="meta">
      <span>{status}</span>
      <span>{latency}s</span>
      <span>{tokens} tok</span>
    </div>
  </div>
  <div class="body">
    <div class="image-panel">
      {image_html}
    </div>
    <div class="text-panel">
      <div class="field"><h4>题干</h4><pre>{stem}</pre></div>
      <div class="field"><h4>答案</h4><pre>{answer}</pre></div>
      <div class="field"><h4>解析</h4><pre>{analysis}</pre></div>
      <div class="field compact"><h4>图像归属</h4><pre>question_image: {question_image}\nanalysis_image: {analysis_image}</pre></div>
      <div class="field compact"><h4>风险标记</h4><pre>stem_requires_image: {stem_requires_image}\nanalysis_requires_image: {analysis_requires_image}\nuncertain_spans: {uncertain_spans}</pre></div>
      <div class="field compact"><h4>错误</h4><pre>{error}</pre></div>
    </div>
  </div>
</section>
""".format(
                case_id=html.escape(str(row.get("case_id", ""))),
                module_zh=html.escape(str(row.get("module_zh", ""))),
                submodule_zh=html.escape(str(row.get("submodule_zh", ""))),
                status=html.escape(str(row.get("status", ""))),
                latency=html.escape(str(row.get("latency_seconds", ""))),
                tokens=html.escape(str(row.get("usage_total_tokens", ""))),
                image_html=(
                    f'<img src="{html.escape(image_rel)}" loading="lazy" />'
                    if image_rel
                    else '<div class="missing">image missing</div>'
                ),
                stem=html.escape(str(row.get("stem_text_md", ""))),
                answer=html.escape(str(row.get("answer_text_md", ""))),
                analysis=html.escape(str(row.get("analysis_text_md", ""))),
                question_image=html.escape(str(row.get("question_image", ""))),
                analysis_image=html.escape(str(row.get("analysis_image", ""))),
                stem_requires_image=html.escape(str(row.get("stem_requires_image", ""))),
                analysis_requires_image=html.escape(str(row.get("analysis_requires_image", ""))),
                uncertain_spans=html.escape(str(row.get("uncertain_spans", ""))),
                error=html.escape(str(row.get("error", ""))),
            )
        )

    doc = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>视觉转录字段审查面板</title>
  <style>
    body {{ margin: 0; font-family: "Microsoft YaHei", Arial, sans-serif; background: #f5f7fb; color: #172033; }}
    header {{ position: sticky; top: 0; z-index: 2; background: #fff; border-bottom: 1px solid #dce3ef; padding: 16px 20px; }}
    h1 {{ margin: 0 0 4px; font-size: 22px; }}
    .summary {{ color: #5c667a; font-size: 14px; }}
    main {{ padding: 18px; display: grid; gap: 16px; }}
    .card {{ background: #fff; border: 1px solid #dce3ef; border-radius: 12px; overflow: hidden; }}
    .card-head {{ display: flex; justify-content: space-between; gap: 16px; padding: 14px 16px; background: #eef4ff; }}
    .case-id {{ font-weight: 700; font-size: 16px; color: #173f7a; }}
    .module {{ color: #5c667a; font-size: 13px; margin-top: 4px; }}
    .meta {{ display: flex; gap: 12px; align-items: center; color: #42516d; font-size: 13px; }}
    .body {{ display: grid; grid-template-columns: minmax(320px, 42%) minmax(420px, 58%); gap: 16px; padding: 16px; }}
    .image-panel img {{ width: 100%; border: 1px solid #e5ebf4; border-radius: 8px; background: #fff; }}
    .missing {{ border: 1px dashed #d1d8e5; border-radius: 8px; min-height: 240px; display: grid; place-items: center; color: #7a869d; }}
    .text-panel {{ display: grid; gap: 12px; }}
    .field {{ border: 1px solid #e5ebf4; border-radius: 8px; overflow: hidden; }}
    .field h4 {{ margin: 0; padding: 8px 10px; font-size: 13px; background: #f8faff; border-bottom: 1px solid #e5ebf4; }}
    .field pre {{ margin: 0; padding: 10px; white-space: pre-wrap; word-break: break-word; font-family: Consolas, "Courier New", monospace; font-size: 12px; line-height: 1.55; }}
    .compact pre {{ font-size: 11px; }}
    @media (max-width: 1200px) {
      .body {{ grid-template-columns: 1fr; }}
    }
  </style>
</head>
<body>
  <header>
    <h1>视觉转录字段审查面板</h1>
    <div class="summary">共 __COUNT__ 题。按图逐字段核对：题干 / 题干图片 / 答案 / 解析 / 解析图片。</div>
  </header>
  <main>
    __CARDS__
  </main>
</body>
</html>
"""
    doc = doc.replace("__COUNT__", str(len(rows))).replace("__CARDS__", "".join(cards))
    out_path.write_text(doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack-manifest", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    pack_manifest_path = Path(args.pack_manifest).resolve()
    run_dir = Path(args.run_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    ensure_dir(out_dir)

    cases = load_pack_cases(pack_manifest_path)
    records = load_records(run_dir)
    rows = [record_to_row(record, cases.get(str(record.get("record_id", "")), {})) for record in records]

    write_csv(rows, out_dir / "transcription_field_review.csv")
    (out_dir / "transcription_field_review.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    build_html(rows, out_dir / "transcription_field_review.html")

    summary = {
        "pack_manifest": str(pack_manifest_path),
        "run_dir": str(run_dir),
        "row_count": len(rows),
        "csv": str(out_dir / "transcription_field_review.csv"),
        "json": str(out_dir / "transcription_field_review.json"),
        "html": str(out_dir / "transcription_field_review.html"),
    }
    (out_dir / "transcription_field_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
