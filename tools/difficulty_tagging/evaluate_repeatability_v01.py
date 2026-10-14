from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = (
    WORKSPACE_ROOT
    / "outputs"
    / "difficulty_tagging_runtime_v01"
    / "math_pdf_gold_holdout_20260914_v01"
    / "staged_evaluation"
    / "staged_eval_plan.public.json"
)
DIMENSIONS = (
    "knowledge_complexity",
    "calculation_complexity",
    "thinking_complexity",
    "reading_conversion_complexity",
    "method_complexity",
    "innovation_complexity",
)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def load_traces(path: Path) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for item in sorted(path.glob("*.difficulty_trace.json")):
        row = json.loads(item.read_text(encoding="utf-8"))
        qid = str(row.get("question_id", "") or "")
        if not qid or qid in values:
            raise ValueError(f"轨迹 question_id 缺失或重复：{item}")
        values[qid] = row
    return values


def selected_ids_and_gate(plan_path: Path, phase: str) -> tuple[list[str], dict[str, Any]]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    phases = plan.get("public_phases")
    if not isinstance(phases, dict) or not isinstance(phases.get(phase), list):
        raise ValueError(f"计划中不存在阶段：{phase}")
    gate = plan.get("release_gates", {}).get("repeatability")
    if not isinstance(gate, dict):
        raise ValueError("计划缺少 repeatability 放行门槛")
    return list(phases[phase]), gate


def evaluate_repeatability(
    first: dict[str, dict[str, Any]],
    second: dict[str, dict[str, Any]],
    selected_ids: list[str],
    gate: dict[str, Any],
) -> dict[str, Any]:
    joined: list[dict[str, Any]] = []
    missing: list[str] = []
    prompt_hash_mismatches: list[str] = []
    for qid in selected_ids:
        left = first.get(qid)
        right = second.get(qid)
        if not left or not right:
            missing.append(qid)
            continue
        if left.get("status") not in {"scored", "needs_review"} or right.get("status") not in {
            "scored",
            "needs_review",
        }:
            missing.append(qid)
            continue
        left_result = left.get("subject_result")
        right_result = right.get("subject_result")
        if not isinstance(left_result, dict) or not isinstance(right_result, dict):
            missing.append(qid)
            continue
        left_hash = str(left.get("provenance", {}).get("prompt_sha256", "") or "")
        right_hash = str(right.get("provenance", {}).get("prompt_sha256", "") or "")
        if not left_hash or left_hash != right_hash:
            prompt_hash_mismatches.append(qid)
        left_dimensions = left_result.get("dimension_scores") or {}
        right_dimensions = right_result.get("dimension_scores") or {}
        joined.append(
            {
                "question_id": qid,
                "left_label": left_result["difficulty_label"],
                "right_label": right_result["difficulty_label"],
                "left_score": int(left_result["total_score"]),
                "right_score": int(right_result["total_score"]),
                "score_drift": abs(int(left_result["total_score"]) - int(right_result["total_score"])),
                "dimension_drift": {
                    key: abs(int(left_dimensions[key]["score"]) - int(right_dimensions[key]["score"]))
                    for key in DIMENSIONS
                },
            }
        )

    same_label_rate = mean(row["left_label"] == row["right_label"] for row in joined) if joined else None
    mean_score_drift = mean(row["score_drift"] for row in joined) if joined else None
    dimension_drift = {
        key: mean(row["dimension_drift"][key] for row in joined) if joined else None
        for key in DIMENSIONS
    }
    checks = {
        "complete_coverage": len(joined) == len(selected_ids),
        "prompt_hash_match": not prompt_hash_mismatches,
        "same_label_rate": same_label_rate is not None
        and same_label_rate >= float(gate["same_label_rate_min"]),
        "mean_absolute_score_drift": mean_score_drift is not None
        and mean_score_drift <= float(gate["mean_absolute_score_drift_max"]),
    }
    return {
        "schema": "difficulty_repeatability_evaluation_v1",
        "selected_count": len(selected_ids),
        "joined_count": len(joined),
        "missing_or_unscored_ids": missing,
        "prompt_hash_mismatch_ids": prompt_hash_mismatches,
        "metrics": {
            "same_label_rate": same_label_rate,
            "mean_absolute_score_drift": mean_score_drift,
            "maximum_score_drift": max((row["score_drift"] for row in joined), default=None),
            "mean_absolute_dimension_drift": dimension_drift,
        },
        "thresholds": gate,
        "gate_checks": checks,
        "gate_passed": all(checks.values()),
        "largest_drifts": sorted(joined, key=lambda row: row["score_drift"], reverse=True)[:10],
    }


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    rate = metrics["same_label_rate"]
    score_drift = metrics["mean_absolute_score_drift"]
    lines = [
        "# 难度打标稳定性复跑报告 v0.1",
        "",
        f"覆盖 {report['joined_count']}/{report['selected_count']} 道；同档率 "
        f"{('-' if rate is None else f'{rate * 100:.1f}%')}，平均总分绝对漂移 "
        f"{('-' if score_drift is None else f'{score_drift:.2f}')} 分。",
        f"提示词哈希不一致题数：{len(report['prompt_hash_mismatch_ids'])}。",
        f"放行结论：{'通过' if report['gate_passed'] else '不通过'}。",
        "",
        "| 检查项 | 结果 |",
        "| --- | --- |",
    ]
    for key, passed in report["gate_checks"].items():
        lines.append(f"| {key} | {'通过' if passed else '不通过'} |")
    lines.extend(["", "| 题目 | 第一次 | 第二次 | 第一次总分 | 第二次总分 | 绝对漂移 |", "| --- | --- | --- | ---: | ---: | ---: |"]) 
    for row in report["largest_drifts"]:
        lines.append(
            f"| {row['question_id']} | {row['left_label']} | {row['right_label']} | "
            f"{row['left_score']} | {row['right_score']} | {row['score_drift']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="比较同一冻结提示词的两次难度打标结果")
    parser.add_argument("--first-traces", type=Path, required=True)
    parser.add_argument("--second-traces", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--phase", default="frozen_validation")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    selected_ids, gate = selected_ids_and_gate(args.plan.resolve(), args.phase)
    report = evaluate_repeatability(
        load_traces(args.first_traces.resolve()),
        load_traces(args.second_traces.resolve()),
        selected_ids,
        gate,
    )
    out_dir = args.out_dir.resolve()
    atomic_write(out_dir / "repeatability_report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    atomic_write(out_dir / "repeatability_report.md", render_markdown(report))
    print(json.dumps({"gate_passed": report["gate_passed"], **report["metrics"]}, ensure_ascii=False))
    return 0 if report["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
