import argparse
import html
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path


def read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - diagnostic script
        return {"_error": str(exc)}


def count_questions(payload):
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("questions", "items", "records", "cases"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
    return 0


def read_progress_jsonl(path: Path):
    events = []
    if not path.exists():
        return events
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            events.append(json.loads(line))
    except Exception as exc:  # pragma: no cover - diagnostic script
        events.append({"event": "progress_read_error", "error": str(exc)})
    return events


def summarize_figure_progress(out_dir: Path):
    figure_dir = out_dir / "04_figure_detection"
    rows = []
    total_done = 0
    total_started = 0
    for path in sorted(figure_dir.glob("prepared_shard_*.progress.jsonl")):
        events = read_progress_jsonl(path)
        started = [item for item in events if item.get("event") == "question_started"]
        completed = [item for item in events if item.get("event") == "question_completed"]
        failed = [item for item in events if item.get("event") == "question_failed"]
        last_event = events[-1] if events else {}
        current = ""
        if started:
            current = str(started[-1].get("question_id", ""))
        if completed and started and completed[-1].get("question_id") == started[-1].get("question_id"):
            current = ""
        if failed:
            current = str(failed[-1].get("question_id", current))
        total_done += len(completed)
        total_started += len(started)
        rows.append(
            {
                "shard": path.name.replace(".progress.jsonl", ""),
                "started_count": len(started),
                "completed_count": len(completed),
                "failed_count": len(failed),
                "current_question_id": current,
                "last_event": last_event,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            }
        )
    return {"started_count": total_started, "completed_count": total_done, "shards": rows}


def list_runtime_processes(tag: str):
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "$p=Get-CimInstance Win32_Process | "
                "Where-Object { $_.Name -match 'python|powershell|cmd' "
                f"-and $_.CommandLine -match '{tag}' }} | "
                "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Depth 4"
            ),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        text = result.stdout.strip()
        if not text:
            return []
        data = json.loads(text)
        if isinstance(data, dict):
            return [data]
        return data if isinstance(data, list) else []
    except Exception as exc:  # pragma: no cover - diagnostic script
        return [{"ProcessId": "?", "Name": "process_check_error", "CommandLine": str(exc)}]


def collect(out_dir: Path):
    source = read_json(out_dir / "source.abs.json")
    state = read_json(out_dir / "state.json") or {}
    gate_dir = out_dir / "01_model_image_need_gate" / "gate"
    candidate_summary = read_json(out_dir / "02_candidate_source" / "figure_candidates.summary.json") or {}
    retry_ids = read_json(out_dir / "03_transcription" / "retry_question_ids.json") or []

    retry_root = out_dir / "03_transcription"
    shard_counts = []
    retry_done = set()
    for shard_dir in sorted(retry_root.glob("retry_shard_*")):
        raw = shard_dir / "raw"
        cases = sorted({p.name.split(".")[0] for p in raw.glob("*.prepared.json")}) if raw.exists() else []
        retry_done.update(cases)
        shard_counts.append({"shard": shard_dir.name, "prepared_count": len(cases), "cases": cases})

    figure_dir = out_dir / "04_figure_detection"
    figure_files = sorted(str(p.relative_to(out_dir)) for p in figure_dir.rglob("*") if p.is_file()) if figure_dir.exists() else []
    prepared_json = out_dir / "05_prepared_merged" / "prepared_merged.json"
    asset_manifest = out_dir / "06_asset_bundle" / "question_asset_manifest_v0.1.json"
    review_html = out_dir / "06_asset_bundle" / "question_asset_review.html"
    asset_audit_summary = out_dir / "07_asset_package_audit" / "asset_package_audit_summary.json"
    asset_audit_html = out_dir / "07_asset_package_audit" / "asset_package_audit.html"
    package_zip = out_dir / "instance_package.zip"
    runtime_summary = out_dir / "runtime_summary.json"

    tag = out_dir.name
    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "out_dir": str(out_dir),
        "state": state,
        "processes": list_runtime_processes(tag),
        "source_count": count_questions(source),
        "gate_files": len(list(gate_dir.glob("*.gate.json"))) if gate_dir.exists() else 0,
        "candidate_count": candidate_summary.get("candidate_count", 0),
        "no_image_count": candidate_summary.get("no_image_count", 0),
        "retry_total": len(retry_ids) if isinstance(retry_ids, list) else 0,
        "retry_done_prepared": len(retry_done),
        "retry_remaining": sorted(set(retry_ids) - retry_done) if isinstance(retry_ids, list) else [],
        "retry_shards": shard_counts,
        "figure_detection_files": len(figure_files),
        "figure_detection_file_sample": figure_files[:20],
        "figure_progress": summarize_figure_progress(out_dir),
        "prepared_merged_exists": prepared_json.exists(),
        "asset_manifest_exists": asset_manifest.exists(),
        "review_html_exists": review_html.exists(),
        "asset_audit_exists": asset_audit_summary.exists(),
        "asset_audit_html_exists": asset_audit_html.exists(),
        "asset_audit": read_json(asset_audit_summary) or {},
        "instance_package_zip_exists": package_zip.exists(),
        "runtime_summary_exists": runtime_summary.exists(),
    }


def render_html(status):
    proc_rows = "\n".join(
        f"<tr><td>{html.escape(str(p.get('ProcessId', '')))}</td>"
        f"<td>{html.escape(str(p.get('Name', '')))}</td>"
        f"<td><code>{html.escape(str(p.get('CommandLine', '')))}</code></td></tr>"
        for p in status["processes"]
    )
    shard_rows = "\n".join(
        f"<tr><td>{html.escape(s['shard'])}</td><td>{s['prepared_count']}</td>"
        f"<td>{html.escape(', '.join(s['cases'][-8:]))}</td></tr>"
        for s in status["retry_shards"]
    )
    figure_progress = status.get("figure_progress", {}) or {}
    figure_rows = "\n".join(
        f"<tr><td>{html.escape(str(s.get('shard', '')))}</td>"
        f"<td>{s.get('started_count', 0)}</td>"
        f"<td>{s.get('completed_count', 0)}</td>"
        f"<td>{s.get('failed_count', 0)}</td>"
        f"<td>{html.escape(str(s.get('current_question_id', '')))}</td>"
        f"<td><code>{html.escape(json.dumps(s.get('last_event', {}), ensure_ascii=False))}</code></td></tr>"
        for s in figure_progress.get("shards", [])
    )
    stage_cards = [
        ("源题", f"{status['source_count']}"),
        ("图片需求判断", f"{status['gate_files']}/{status['source_count']}"),
        ("需要抠图", f"{status['candidate_count']}"),
        ("无需抠图", f"{status['no_image_count']}"),
        ("补转录", f"{status['retry_done_prepared']}/{status['retry_total']}"),
        ("图片检测逐题", f"{figure_progress.get('completed_count', 0)}/{status['candidate_count']}"),
        ("抠图文件", f"{status['figure_detection_files']}"),
        ("合并完成", "是" if status["prepared_merged_exists"] else "否"),
        ("审核页", "是" if status["review_html_exists"] else "否"),
        ("图片包审核", "是" if status["asset_audit_exists"] else "否"),
        ("实例包", "是" if status["instance_package_zip_exists"] else "否"),
    ]
    cards = "\n".join(f"<div class='card'><b>{html.escape(k)}</b><span>{html.escape(v)}</span></div>" for k, v in stage_cards)
    return f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>Runtime Live Status</title>
<style>
body {{ font-family: "Microsoft YaHei", sans-serif; margin: 24px; color: #18202f; background: #f7f4ee; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 16px 0; }}
.card {{ background: white; border: 1px solid #e1d7c7; border-radius: 12px; padding: 14px; }}
.card b {{ display: block; color: #516078; font-size: 13px; }}
.card span {{ display: block; font-size: 26px; margin-top: 8px; }}
table {{ border-collapse: collapse; width: 100%; background: white; margin: 16px 0; }}
td, th {{ border: 1px solid #e1d7c7; padding: 8px; vertical-align: top; }}
code {{ white-space: pre-wrap; font-size: 12px; }}
.path {{ color: #516078; word-break: break-all; }}
</style>
<h1>208 全量运行实时状态</h1>
<p>更新时间：{html.escape(status['updated_at'])}</p>
<p class="path">{html.escape(status['out_dir'])}</p>
<div class="cards">{cards}</div>
<h2>当前状态</h2>
<pre>{html.escape(json.dumps(status['state'], ensure_ascii=False, indent=2))}</pre>
<h2>补转录分片</h2>
<table><tr><th>分片</th><th>完成数</th><th>最近完成 case</th></tr>{shard_rows}</table>
<h2>图片检测分片</h2>
<table><tr><th>分片</th><th>已开始</th><th>已完成</th><th>失败</th><th>当前题</th><th>最近事件</th></tr>{figure_rows}</table>
<h2>活进程</h2>
<table><tr><th>PID</th><th>名称</th><th>命令</th></tr>{proc_rows}</table>
</html>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    out_dir = Path(args.out_dir).expanduser().resolve()
    while True:
        status = collect(out_dir)
        (out_dir / "live_runtime_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "live_runtime_status.html").write_text(render_html(status), encoding="utf-8")
        if args.once:
            break
        if status["runtime_summary_exists"] and status["instance_package_zip_exists"]:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
