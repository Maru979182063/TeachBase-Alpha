from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
HOLDOUT_ROOT = (
    WORKSPACE_ROOT
    / "outputs"
    / "difficulty_tagging_runtime_v01"
    / "math_pdf_gold_holdout_20260914_v01"
)
DEFAULT_GOLD = HOLDOUT_ROOT / "itemized" / "gold_items.private.jsonl"
DEFAULT_TRACES = (
    WORKSPACE_ROOT
    / "outputs"
    / "difficulty_tagging_runtime_v01"
    / "math_pdf_gold_holdout_20260914_blind_v01"
    / "traces"
)
DEFAULT_UPSTREAM_TRACES = (
    WORKSPACE_ROOT
    / "outputs"
    / "knowledge_tagging_v0_1"
    / "math_pdf_gold_holdout_20260914_v01"
)
DEFAULT_OUT = HOLDOUT_ROOT / "staged_evaluation"
LABELS = {1: "易", 2: "较易", 3: "中档", 4: "较难", 5: "困难"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_observed_ids(path: Path) -> set[str]:
    observed: set[str] = set()
    if not path.is_dir():
        return observed
    for item in sorted(path.glob("*.difficulty_trace.json")):
        value = json.loads(item.read_text(encoding="utf-8"))
        qid = str(value.get("question_id", "") or "")
        if qid:
            observed.add(qid)
    return observed


def load_unavailable_upstream_ids(path: Path) -> set[str]:
    unavailable: set[str] = set()
    if not path.is_dir():
        return unavailable
    for item in sorted(path.glob("*.tagging_trace.json")):
        value = json.loads(item.read_text(encoding="utf-8"))
        qid = str(value.get("question_id", "") or "")
        final_result = value.get("final_result")
        decision = final_result.get("decision_profile", {}) if isinstance(final_result, dict) else {}
        if qid and not (
            value.get("status") == "tagged"
            and isinstance(decision, dict)
            and decision.get("release_decision") == "accept"
        ):
            unavailable.add(qid)
    return unavailable


def pick_evenly(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count < 0 or count > len(rows):
        raise ValueError(f"无法从 {len(rows)} 条记录中选择 {count} 条")
    if count == 0:
        return []
    if count == 1:
        return [rows[len(rows) // 2]]
    indexes = [round(index * (len(rows) - 1) / (count - 1)) for index in range(count)]
    if len(indexes) != len(set(indexes)):
        raise ValueError("等距抽样产生重复位置")
    return [rows[index] for index in indexes]


def choose_phase(
    rows: list[dict[str, Any]],
    count: int,
    *,
    observed_ids: set[str],
    prefer_observed: bool,
) -> list[dict[str, Any]]:
    preferred = [
        row
        for row in rows
        if (row["gold_item_id"] in observed_ids) is prefer_observed
    ]
    fallback = [row for row in rows if row not in preferred]
    if len(preferred) >= count:
        return pick_evenly(preferred, count)
    selected = list(preferred)
    selected.extend(pick_evenly(fallback, count - len(selected)))
    return sorted(selected, key=lambda row: int(row["source_item_ordinal"]))


def build_plan(
    gold_rows: list[dict[str, Any]],
    observed_ids: set[str],
    *,
    calibration_per_level: int,
    validation_per_level: int,
    unavailable_upstream_ids: set[str] | None = None,
) -> dict[str, Any]:
    unavailable_upstream_ids = unavailable_upstream_ids or set()
    by_level: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in gold_rows:
        by_level[int(row["gold_level"])].append(row)
    if set(by_level) != set(LABELS):
        raise ValueError(f"金标必须覆盖五档，实际为 {sorted(by_level)}")
    for rows in by_level.values():
        rows.sort(key=lambda row: (str(row["source_id"]), int(row["source_item_ordinal"])))

    phases: dict[str, list[dict[str, Any]]] = {
        "calibration": [],
        "frozen_validation": [],
        "full_remainder": [],
    }
    for level in range(1, 6):
        pool = by_level[level]
        early_phase_pool = [
            row for row in pool if row["gold_item_id"] not in unavailable_upstream_ids
        ]
        calibration = choose_phase(
            early_phase_pool,
            calibration_per_level,
            observed_ids=observed_ids,
            prefer_observed=True,
        )
        calibration_ids = {row["gold_item_id"] for row in calibration}
        validation_pool = [
            row for row in early_phase_pool if row["gold_item_id"] not in calibration_ids
        ]
        validation = choose_phase(
            validation_pool,
            validation_per_level,
            observed_ids=observed_ids,
            prefer_observed=False,
        )
        validation_ids = {row["gold_item_id"] for row in validation}
        full_remainder = [
            row
            for row in pool
            if row["gold_item_id"] not in calibration_ids
            and row["gold_item_id"] not in validation_ids
        ]
        phases["calibration"].extend(calibration)
        phases["frozen_validation"].extend(validation)
        phases["full_remainder"].extend(full_remainder)

    assignment: dict[str, str] = {}
    for phase, rows in phases.items():
        for row in rows:
            qid = row["gold_item_id"]
            if qid in assignment:
                raise ValueError(f"题目重复分配：{qid}")
            assignment[qid] = phase
    expected_ids = {row["gold_item_id"] for row in gold_rows}
    if set(assignment) != expected_ids:
        raise ValueError("分阶段计划没有完整且互斥地覆盖金标集")

    private_phases: dict[str, list[dict[str, Any]]] = {}
    public_phases: dict[str, list[str]] = {}
    for phase, rows in phases.items():
        ordered = sorted(rows, key=lambda row: row["gold_item_id"])
        public_phases[phase] = [row["gold_item_id"] for row in ordered]
        private_phases[phase] = [
            {
                "question_id": row["gold_item_id"],
                "gold_level": int(row["gold_level"]),
                "gold_label": row["gold_label"],
                "source_id": row["source_id"],
                "source_item_ordinal": int(row["source_item_ordinal"]),
                "observed_before_plan_freeze": row["gold_item_id"] in observed_ids,
            }
            for row in ordered
        ]

    strict_blind_by_level: dict[str, dict[str, int | str]] = {}
    for level in range(1, 6):
        validation_rows = [row for row in private_phases["frozen_validation"] if row["gold_level"] == level]
        strict_count = sum(not row["observed_before_plan_freeze"] for row in validation_rows)
        strict_blind_by_level[str(level)] = {
            "label": LABELS[level],
            "validation_count": len(validation_rows),
            "strictly_unobserved_count": strict_count,
        }

    return {
        "schema": "difficulty_staged_evaluation_plan_v1",
        "created_at": utc_now(),
        "plan_status": "frozen",
        "selection_method": "gold-level stratification plus deterministic even positional coverage",
        "selection_semantics": "Selection does not inspect question text or use lexical rules.",
        "counts": {phase: len(rows) for phase, rows in public_phases.items()},
        "observed_before_plan_freeze_count": len(observed_ids.intersection(expected_ids)),
        "upstream_unavailable_ids": sorted(unavailable_upstream_ids.intersection(expected_ids)),
        "strict_blind_validation_by_level": strict_blind_by_level,
        "known_limitation": (
            "All level-1 items were already called before this plan was frozen. "
            "Level-1 validation is suitable for internal stabilization only; a new external level-1 set is required for a clean release claim."
        ),
        "public_phases": public_phases,
        "private_phases": private_phases,
        "release_gates": {
            "calibration": {
                "purpose": "prompt diagnosis and revision; results may be inspected",
                "required_scored_rate_min": 0.96,
                "adjacent_accuracy_min": 0.95,
                "level_mae_max": 0.40,
                "absolute_mean_score_bias_max": 4.0,
            },
            "frozen_validation": {
                "purpose": "no prompt edits after the run starts",
                "exact_accuracy_min": 0.75,
                "adjacent_accuracy_min": 0.95,
                "level_mae_max": 0.30,
                "per_level_recall_min": 0.60,
                "score_mae_max": 5.0,
                "absolute_mean_score_bias_max": 2.5,
            },
            "repeatability": {
                "purpose": "rerun the frozen validation with the identical prompt hash",
                "same_label_rate_min": 0.90,
                "mean_absolute_score_drift_max": 3.0,
                "prompt_hash_must_match": True,
            },
            "full_release": {
                "requires": [
                    "frozen_validation_pass",
                    "repeatability_pass",
                    "zero_unresolved_structural_contract_failures",
                ],
                "level_1_external_refresh_required_for_release_claim": True,
            },
        },
    }


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def render_protocol(plan: dict[str, Any]) -> str:
    blind = plan["strict_blind_validation_by_level"]
    lines = [
        "# 数学五档难度分阶段评测协议 v0.1",
        "",
        "## 执行顺序",
        "",
        "1. 校准集 25 道：每档 5 道。允许查看金标、六维误差与错误原因，并据此修改 YAML 提示词。",
        "2. 冻结提示词：记录 prompt version 与 SHA-256，之后不得再改提示词。",
        "3. 冻结验证集 20 道：每档 4 道。只在全部完成后统一揭示指标。",
        "4. 稳定性复跑：同一模型、同一提示词哈希复跑验证集，比较档位一致率和分数漂移。",
        "5. 通过全部闸门后，才执行余量 47 道；未通过则回到第 1 步并升提示词版本。",
        "",
        "## 数据纪律",
        "",
        "- 校准集、验证集、余量集互斥且合计覆盖全部 92 道。",
        "- 抽样只使用金标档位和题号位置，不读取题干做关键词或正则分类。",
        "- 模型输入继续只使用遮蔽后的公开题面与上游知识标签，不注入金标字段。",
        "- 旧版已经产生的 36 条轨迹属于探索数据，不作为冻结验证成绩。",
        "",
        "## 严格盲测状态",
        "",
        "| 档位 | 验证题数 | 从未调用题数 |",
        "| --- | ---: | ---: |",
    ]
    for level in range(1, 6):
        item = blind[str(level)]
        lines.append(f"| {item['label']} | {item['validation_count']} | {item['strictly_unobserved_count']} |")
    lines.extend(
        [
            "",
            "‘易’档 21 道在计划冻结前已全部调用，因此本批中的易档验证只能用于内部稳定性判断，不能包装成严格未见测试。正式发布结论前需要补充一批新的易档外部题。",
            "",
            "## 放行原则",
            "",
            "校准集用于找问题，不用于宣称效果；冻结验证和同哈希复跑同时通过后才能全量。任何结构契约失败、提示词哈希变化或人工发现系统性偏差，都阻断全量放行。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="构建五档难度校准、冻结验证和全量余量计划")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--observed-traces", type=Path, default=DEFAULT_TRACES)
    parser.add_argument("--upstream-traces", type=Path, default=DEFAULT_UPSTREAM_TRACES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--calibration-per-level", type=int, default=5)
    parser.add_argument("--validation-per-level", type=int, default=4)
    parser.add_argument(
        "--force",
        action="store_true",
        help="显式覆盖既有计划；正式评测应改用新的输出目录而不是覆盖",
    )
    args = parser.parse_args()

    out_dir = args.out_dir.resolve()
    planned_outputs = (
        out_dir / "staged_eval_plan.public.json",
        out_dir / "staged_eval_plan.private.json",
        out_dir / "staged_eval_protocol.md",
    )
    if not args.force and any(path.exists() for path in planned_outputs):
        raise ValueError(
            f"评测计划已冻结，拒绝覆盖：{out_dir}；如需新计划请使用新的 --out-dir"
        )
    plan = build_plan(
        load_jsonl(args.gold.resolve()),
        load_observed_ids(args.observed_traces.resolve()),
        calibration_per_level=args.calibration_per_level,
        validation_per_level=args.validation_per_level,
        unavailable_upstream_ids=load_unavailable_upstream_ids(args.upstream_traces.resolve()),
    )
    public = {
        key: value
        for key, value in plan.items()
        if key not in {"private_phases", "strict_blind_validation_by_level"}
    }
    atomic_write(out_dir / "staged_eval_plan.public.json", json.dumps(public, ensure_ascii=False, indent=2) + "\n")
    atomic_write(out_dir / "staged_eval_plan.private.json", json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    atomic_write(out_dir / "staged_eval_protocol.md", render_protocol(plan))
    print(
        json.dumps(
            {
                "counts": plan["counts"],
                "observed_before_plan_freeze_count": plan["observed_before_plan_freeze_count"],
                "strict_blind_validation_by_level": plan["strict_blind_validation_by_level"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
