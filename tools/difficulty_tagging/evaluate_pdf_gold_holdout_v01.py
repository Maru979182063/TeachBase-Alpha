from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
HOLDOUT_ROOT = (
    WORKSPACE_ROOT
    / "outputs"
    / "difficulty_tagging_runtime_v01"
    / "math_pdf_gold_holdout_20260914_v01"
)
DEFAULT_GOLD = HOLDOUT_ROOT / "itemized" / "gold_items.private.jsonl"
DEFAULT_RESULTS = (
    WORKSPACE_ROOT
    / "outputs"
    / "difficulty_tagging_runtime_v01"
    / "math_pdf_gold_holdout_20260914_blind_v01"
    / "traces"
)
DEFAULT_OUT = DEFAULT_RESULTS.parent
LABELS = {1: "易", 2: "较易", 3: "中档", 4: "较难", 5: "困难"}
DIMENSIONS = (
    ("knowledge_complexity", "知识点复杂度"),
    ("calculation_complexity", "计算复杂度"),
    ("thinking_complexity", "思维复杂度"),
    ("reading_conversion_complexity", "阅读转换复杂度"),
    ("method_complexity", "方法复杂度"),
    ("innovation_complexity", "创新复杂度"),
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_traces(path: Path) -> list[dict[str, Any]]:
    return [json.loads(item.read_text(encoding="utf-8")) for item in sorted(path.glob("*.difficulty_trace.json"))]


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def quadratic_weighted_kappa(pairs: list[tuple[int, int]], levels: int = 5) -> float | None:
    if not pairs:
        return None
    matrix = [[0 for _ in range(levels)] for _ in range(levels)]
    gold_counts = [0 for _ in range(levels)]
    pred_counts = [0 for _ in range(levels)]
    for gold, pred in pairs:
        matrix[gold - 1][pred - 1] += 1
        gold_counts[gold - 1] += 1
        pred_counts[pred - 1] += 1
    observed = 0.0
    expected = 0.0
    total = len(pairs)
    denominator = float((levels - 1) ** 2)
    for i in range(levels):
        for j in range(levels):
            weight = ((i - j) ** 2) / denominator
            observed += weight * matrix[i][j] / total
            expected += weight * (gold_counts[i] * pred_counts[j]) / (total * total)
    if expected == 0:
        return 1.0 if observed == 0 else None
    return 1.0 - observed / expected


def pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def number(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def load_selected_ids(plan_path: Path | None, phase: str | None) -> set[str] | None:
    if plan_path is None:
        if phase:
            raise ValueError("指定 --phase 时必须同时指定 --plan")
        return None
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    phases = plan.get("public_phases")
    if not isinstance(phases, dict):
        raise ValueError("评测计划缺少 public_phases")
    if not phase or phase not in phases:
        raise ValueError(f"评测阶段不存在：{phase}")
    values = phases[phase]
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise ValueError(f"评测阶段 {phase} 的题目清单无效")
    return set(values)


def evaluate(
    gold_path: Path,
    traces_path: Path,
    selected_ids: set[str] | None = None,
    phase: str | None = None,
) -> dict[str, Any]:
    gold_rows = {row["gold_item_id"]: row for row in load_jsonl(gold_path)}
    if selected_ids is not None:
        missing = selected_ids.difference(gold_rows)
        if missing:
            raise ValueError(f"评测计划包含未知题目：{sorted(missing)}")
        gold_rows = {key: value for key, value in gold_rows.items() if key in selected_ids}
    traces = {row["question_id"]: row for row in load_traces(traces_path)}
    joined: list[dict[str, Any]] = []
    statuses = Counter()
    for item_id, gold in gold_rows.items():
        trace = traces.get(item_id)
        status = str(trace.get("status", "missing")) if trace else "missing"
        statuses[status] += 1
        if not trace or status not in {"scored", "needs_review"}:
            continue
        result = trace.get("subject_result")
        if not isinstance(result, dict):
            continue
        prediction = trace.get("difficulty") if isinstance(trace.get("difficulty"), dict) else {}
        pred_level = int(prediction.get("difficulty_level") or result["difficulty_level"])
        gold_level = int(gold["gold_level"])
        pred_dimensions = result.get("dimension_scores") or {}
        semantic = result.get("semantic_reasoning") if isinstance(result.get("semantic_reasoning"), dict) else {}
        solution_graph = semantic.get("shortest_solution_graph") if isinstance(semantic.get("shortest_solution_graph"), dict) else {}
        graph_nodes = solution_graph.get("nodes") if isinstance(solution_graph.get("nodes"), list) else []
        knowledge_units = semantic.get("required_knowledge_units") if isinstance(semantic.get("required_knowledge_units"), list) else []
        calculation_steps = semantic.get("independent_calculation_steps") if isinstance(semantic.get("independent_calculation_steps"), list) else []
        decision_nodes = semantic.get("independent_decision_nodes") if isinstance(semantic.get("independent_decision_nodes"), list) else []
        reading = semantic.get("reading_transformation") if isinstance(semantic.get("reading_transformation"), dict) else {}
        method_entry = semantic.get("method_entry") if isinstance(semantic.get("method_entry"), dict) else {}
        innovation = semantic.get("innovation_assessment") if isinstance(semantic.get("innovation_assessment"), dict) else {}
        joined.append(
            {
                "question_id": item_id,
                "gold_level": gold_level,
                "gold_label": gold["gold_label"],
                "gold_score": int(gold["stated_total"]),
                "pred_level": pred_level,
                "pred_label": result["difficulty_label"],
                "pred_score": int(result["total_score"]),
                "level_delta": pred_level - gold_level,
                "score_delta": int(result["total_score"]) - int(gold["stated_total"]),
                "gold_dimensions": gold["dimension_scores"],
                "pred_dimensions": {
                    key: int(pred_dimensions[key]["score"]) for key, _ in DIMENSIONS
                },
                "confidence": float(result.get("difficulty_confidence", 0)),
                "status": status,
                "prompt_version": trace.get("provenance", {}).get("prompt_version", ""),
                "prompt_sha256": trace.get("provenance", {}).get("prompt_sha256", ""),
                "attempt_count": int(trace.get("model_call", {}).get("attempt_count", 0)),
                "semantic_reasoning": {
                    "present": bool(semantic),
                    "graph_node_count": len(graph_nodes),
                    "knowledge_unit_count": len(knowledge_units),
                    "calculation_step_count": len(calculation_steps),
                    "decision_node_count": len(decision_nodes),
                    "method_entry_type": str(method_entry.get("entry_type", "") or ""),
                    "unstated_key_move_count": len(method_entry.get("unstated_key_moves") or []),
                    "reading_recommended_band": reading.get("recommended_band"),
                    "method_recommended_band": method_entry.get("recommended_band"),
                    "innovation_recommended_band": innovation.get("recommended_band"),
                },
            }
        )

    pairs = [(row["gold_level"], row["pred_level"]) for row in joined]
    confusion = [[0 for _ in range(5)] for _ in range(5)]
    for gold_level, pred_level in pairs:
        confusion[gold_level - 1][pred_level - 1] += 1
    exact = mean(row["gold_level"] == row["pred_level"] for row in joined) if joined else None
    adjacent = mean(abs(row["level_delta"]) <= 1 for row in joined) if joined else None
    level_mae = mean(abs(row["level_delta"]) for row in joined) if joined else None
    score_mae = mean(abs(row["score_delta"]) for row in joined) if joined else None
    score_bias = mean(row["score_delta"] for row in joined) if joined else None

    by_gold_level: dict[str, Any] = {}
    for level in range(1, 6):
        rows = [row for row in joined if row["gold_level"] == level]
        level_dimension_metrics: dict[str, Any] = {}
        for key, label in DIMENSIONS:
            deltas = [row["pred_dimensions"][key] - row["gold_dimensions"][key] for row in rows]
            level_dimension_metrics[key] = {
                "label": label,
                "mae": mean(abs(delta) for delta in deltas) if deltas else None,
                "mean_bias": mean(deltas) if deltas else None,
            }
        by_gold_level[str(level)] = {
            "label": LABELS[level],
            "gold_count": sum(1 for row in gold_rows.values() if int(row["gold_level"]) == level),
            "scored_count": len(rows),
            "exact_recall": mean(row["pred_level"] == level for row in rows) if rows else None,
            "adjacent_rate": mean(abs(row["level_delta"]) <= 1 for row in rows) if rows else None,
            "mean_level_delta": mean(row["level_delta"] for row in rows) if rows else None,
            "mean_score_delta": mean(row["score_delta"] for row in rows) if rows else None,
            "predicted_distribution": dict(sorted(Counter(row["pred_label"] for row in rows).items())),
            "dimension_metrics": level_dimension_metrics,
        }

    dimension_metrics: dict[str, Any] = {}
    for key, label in DIMENSIONS:
        deltas = [row["pred_dimensions"][key] - row["gold_dimensions"][key] for row in joined]
        dimension_metrics[key] = {
            "label": label,
            "exact_rate": mean(delta == 0 for delta in deltas) if deltas else None,
            "mae": mean(abs(delta) for delta in deltas) if deltas else None,
            "mean_bias": mean(deltas) if deltas else None,
        }

    boundary_scores = (30, 40, 65, 86)
    boundary_rows = [
        row for row in joined if min(abs(row["gold_score"] - boundary) for boundary in boundary_scores) <= 2
    ]
    largest_errors = sorted(
        joined,
        key=lambda row: (abs(row["level_delta"]), abs(row["score_delta"])),
        reverse=True,
    )[:15]
    attempts = Counter(row["attempt_count"] for row in joined)
    confidences = [row["confidence"] for row in joined]
    prompt_versions = sorted(set(row["prompt_version"] for row in joined))
    prompt_hashes = sorted(set(row["prompt_sha256"] for row in joined))
    semantic_rows = [row["semantic_reasoning"] for row in joined if row["semantic_reasoning"]["present"]]
    return {
        "schema": "difficulty_gold_evaluation_v1",
        "evaluation_phase": phase or "all",
        "gold_count": len(gold_rows),
        "trace_count": len(traces),
        "scored_count": len(joined),
        "status_counts": dict(sorted(statuses.items())),
        "metrics": {
            "exact_accuracy": exact,
            "adjacent_accuracy": adjacent,
            "level_mae": level_mae,
            "quadratic_weighted_kappa": quadratic_weighted_kappa(pairs),
            "score_mae": score_mae,
            "mean_score_bias": score_bias,
        },
        "confusion_matrix": {
            "row_labels": [LABELS[index] for index in range(1, 6)],
            "column_labels": [LABELS[index] for index in range(1, 6)],
            "values": confusion,
        },
        "by_gold_level": by_gold_level,
        "dimension_metrics": dimension_metrics,
        "boundary_slice": {
            "definition": "gold score within 2 points of 30, 40, 65, or 86",
            "count": len(boundary_rows),
            "exact_accuracy": mean(row["gold_level"] == row["pred_level"] for row in boundary_rows) if boundary_rows else None,
            "adjacent_accuracy": mean(abs(row["level_delta"]) <= 1 for row in boundary_rows) if boundary_rows else None,
        },
        "predicted_distribution": dict(sorted(Counter(row["pred_label"] for row in joined).items())),
        "attempt_distribution": {str(key): value for key, value in sorted(attempts.items())},
        "confidence": {
            "mean": mean(confidences) if confidences else None,
            "min": min(confidences) if confidences else None,
            "max": max(confidences) if confidences else None,
        },
        "semantic_reasoning_metrics": {
            "coverage_rate": len(semantic_rows) / len(joined) if joined else None,
            "mean_graph_node_count": mean(row["graph_node_count"] for row in semantic_rows) if semantic_rows else None,
            "mean_knowledge_unit_count": mean(row["knowledge_unit_count"] for row in semantic_rows) if semantic_rows else None,
            "mean_calculation_step_count": mean(row["calculation_step_count"] for row in semantic_rows) if semantic_rows else None,
            "mean_decision_node_count": mean(row["decision_node_count"] for row in semantic_rows) if semantic_rows else None,
            "mean_unstated_key_move_count": mean(row["unstated_key_move_count"] for row in semantic_rows) if semantic_rows else None,
            "method_entry_distribution": dict(
                sorted(Counter(row["method_entry_type"] for row in semantic_rows).items())
            ),
        },
        "provenance": {
            "prompt_versions": prompt_versions,
            "prompt_sha256": prompt_hashes,
        },
        "largest_errors": largest_errors,
        "thresholds": {
            "exact_accuracy_min": 0.70,
            "adjacent_accuracy_min": 0.95,
            "level_mae_max": 0.35,
            "per_level_recall_min": 0.60,
        },
    }


def assess_phase_gate(report: dict[str, Any], gate: dict[str, Any], phase: str) -> dict[str, Any]:
    metrics = report["metrics"]
    scored_rate = report["scored_count"] / report["gold_count"] if report["gold_count"] else 0.0
    checks: dict[str, bool] = {"complete_coverage": report["scored_count"] == report["gold_count"]}
    if phase == "calibration":
        checks.update(
            {
                "required_scored_rate": scored_rate >= float(gate["required_scored_rate_min"]),
                "adjacent_accuracy": metrics["adjacent_accuracy"] is not None
                and metrics["adjacent_accuracy"] >= float(gate["adjacent_accuracy_min"]),
                "level_mae": metrics["level_mae"] is not None
                and metrics["level_mae"] <= float(gate["level_mae_max"]),
                "absolute_mean_score_bias": metrics["mean_score_bias"] is not None
                and abs(metrics["mean_score_bias"]) <= float(gate["absolute_mean_score_bias_max"]),
            }
        )
    elif phase == "frozen_validation":
        recalls = [report["by_gold_level"][str(level)]["exact_recall"] for level in range(1, 6)]
        checks.update(
            {
                "exact_accuracy": metrics["exact_accuracy"] is not None
                and metrics["exact_accuracy"] >= float(gate["exact_accuracy_min"]),
                "adjacent_accuracy": metrics["adjacent_accuracy"] is not None
                and metrics["adjacent_accuracy"] >= float(gate["adjacent_accuracy_min"]),
                "level_mae": metrics["level_mae"] is not None
                and metrics["level_mae"] <= float(gate["level_mae_max"]),
                "per_level_recall": all(
                    value is not None and value >= float(gate["per_level_recall_min"])
                    for value in recalls
                ),
                "score_mae": metrics["score_mae"] is not None
                and metrics["score_mae"] <= float(gate["score_mae_max"]),
                "absolute_mean_score_bias": metrics["mean_score_bias"] is not None
                and abs(metrics["mean_score_bias"]) <= float(gate["absolute_mean_score_bias_max"]),
            }
        )
    else:
        raise ValueError(f"阶段没有可执行的放行闸门：{phase}")
    return {
        "phase": phase,
        "scored_rate": scored_rate,
        "thresholds": gate,
        "checks": checks,
        "passed": all(checks.values()),
    }


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    lines = [
        "# 数学五档难度盲测报告 v0.1",
        "",
        "## 结论",
        "",
        f"金标 {report['gold_count']} 道，已获得可评测结果 {report['scored_count']} 道。",
        f"五档完全一致率 {pct(metrics['exact_accuracy'])}，相邻档一致率 {pct(metrics['adjacent_accuracy'])}，",
        f"档位 MAE {number(metrics['level_mae'])}，二次加权 Kappa {number(metrics['quadratic_weighted_kappa'])}。",
        f"总分 MAE {number(metrics['score_mae'], 2)}，平均分偏差 {number(metrics['mean_score_bias'], 2)}。",
        "",
        "本报告是盲测结果：模型调用前已遮蔽来源文件档位、六维评分表、总分和难度解释。",
        "该批 PDF 与先前业务样例 DOCX 存在同源关系，因此属于外部详细版回归集，不应宣称为完全独立的新分布泛化集。",
    ]
    if isinstance(report.get("phase_gate"), dict):
        gate_result = report["phase_gate"]
        lines.extend(
            [
                "",
                f"阶段闸门：{gate_result['phase']}，结论 {'通过' if gate_result['passed'] else '不通过'}。",
                "检查项：" + "、".join(
                    f"{key}={'通过' if passed else '不通过'}"
                    for key, passed in gate_result["checks"].items()
                ) + "。",
            ]
        )
    lines.extend(
        [
        "",
        "## 五档混淆矩阵",
        "",
        "| 金标 \\ 预测 | 易 | 较易 | 中档 | 较难 | 困难 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for label, row in zip(report["confusion_matrix"]["row_labels"], report["confusion_matrix"]["values"], strict=True):
        lines.append(f"| {label} | " + " | ".join(str(value) for value in row) + " |")

    lines.extend(["", "## 分档表现", "", "| 金标档位 | 已评分/总数 | 精确召回 | 相邻档率 | 平均档位偏差 | 平均分偏差 | 预测分布 |", "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]) 
    for level in range(1, 6):
        item = report["by_gold_level"][str(level)]
        distribution = "、".join(f"{key}{value}" for key, value in item["predicted_distribution"].items()) or "-"
        lines.append(
            f"| {item['label']} | {item['scored_count']}/{item['gold_count']} | {pct(item['exact_recall'])} | "
            f"{pct(item['adjacent_rate'])} | {number(item['mean_level_delta'], 2)} | {number(item['mean_score_delta'], 2)} | {distribution} |"
        )

    lines.extend(["", "## 六维偏差", "", "| 维度 | 完全一致率 | MAE | 平均偏差 |", "| --- | ---: | ---: | ---: |"]) 
    for key, _ in DIMENSIONS:
        item = report["dimension_metrics"][key]
        lines.append(f"| {item['label']} | {pct(item['exact_rate'])} | {number(item['mae'], 2)} | {number(item['mean_bias'], 2)} |")

    boundary = report["boundary_slice"]
    semantic = report["semantic_reasoning_metrics"]
    lines.extend(
        [
            "",
            "## 边界题与运行质量",
            "",
            f"距 30、40、65、86 分边界不超过 2 分的题共 {boundary['count']} 道；完全一致率 {pct(boundary['exact_accuracy'])}，相邻档率 {pct(boundary['adjacent_accuracy'])}。",
            f"预测档位分布：{json.dumps(report['predicted_distribution'], ensure_ascii=False)}。",
            f"调用尝试次数分布：{json.dumps(report['attempt_distribution'], ensure_ascii=False)}。",
            f"置信度均值 {number(report['confidence']['mean'])}，范围 {number(report['confidence']['min'])} 至 {number(report['confidence']['max'])}。",
            "",
            "## 语义中间层",
            "",
            f"覆盖率 {pct(semantic['coverage_rate'])}；平均依赖图节点数 {number(semantic['mean_graph_node_count'], 2)}，"
            f"平均必要知识单元数 {number(semantic['mean_knowledge_unit_count'], 2)}，"
            f"平均独立计算步骤数 {number(semantic['mean_calculation_step_count'], 2)}，"
            f"平均独立决策节点数 {number(semantic['mean_decision_node_count'], 2)}，"
            f"平均未明示关键动作数 {number(semantic['mean_unstated_key_move_count'], 2)}。",
            f"方法入口分布：{json.dumps(semantic['method_entry_distribution'], ensure_ascii=False)}。",
            "",
            "## 最大偏差样本",
            "",
            "| 题目 | 金标 | 预测 | 金标分 | 预测分 | 档差 | 分差 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["largest_errors"]:
        lines.append(
            f"| {row['question_id']} | {row['gold_label']} | {row['pred_label']} | {row['gold_score']} | "
            f"{row['pred_score']} | {row['level_delta']:+d} | {row['score_delta']:+d} |"
        )

    lines.extend(
        [
            "",
            "## 工程判定",
            "",
            "试运行门槛为：完全一致率 >= 70%，相邻档率 >= 95%，档位 MAE <= 0.35，且各档召回率 >= 60%。",
            "这些阈值只用于首轮工程判断；最终教研门槛应以教师双人复标的一致性为上限参照。",
            "",
            f"状态统计：{json.dumps(report['status_counts'], ensure_ascii=False)}。",
            f"提示词版本：{json.dumps(report['provenance']['prompt_versions'], ensure_ascii=False)}。",
            f"提示词哈希：{json.dumps(report['provenance']['prompt_sha256'], ensure_ascii=False)}。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="比较数学 PDF 私有金标与盲测难度结果")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--traces", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--plan", type=Path)
    parser.add_argument(
        "--phase",
        choices=("calibration", "frozen_validation", "full_remainder"),
    )
    args = parser.parse_args()
    plan_path = args.plan.resolve() if args.plan else None
    selected_ids = load_selected_ids(plan_path, args.phase)
    report = evaluate(args.gold.resolve(), args.traces.resolve(), selected_ids, args.phase)
    if plan_path and args.phase in {"calibration", "frozen_validation"}:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        gate = plan.get("release_gates", {}).get(args.phase)
        if not isinstance(gate, dict):
            raise ValueError(f"计划缺少 {args.phase} 放行门槛")
        report["phase_gate"] = assess_phase_gate(report, gate, args.phase)
    atomic_write(args.out_dir / "evaluation_report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    atomic_write(args.out_dir / "evaluation_report.md", render_markdown(report))
    print(json.dumps({"scored_count": report["scored_count"], **report["metrics"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
