from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "outputs" / "min_kp_question_coverage_v0.1" / "curated_model_run_v0.2"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def main() -> None:
    result = load_json(RUN / "curated_min_kp_eval_v0.2.json")
    summaries = result["summaries"]
    by_group = result["by_group"]
    issues = result["issues"]
    issue_counter = Counter(i.get("issue_type") or "unknown" for i in issues)

    lines = [
        "# 二轮金标落位测试报告 v0.2",
        "",
        "生成时间：2026-06-17",
        "",
        "## 口径",
        "",
        "- `clean_30`：只使用金标清洗后可直接用的 30 条题面。",
        "- `expanded_140`：`clean_30` 加上 110 条可暂用但建议后续精裁的题面。",
        "- 预测阶段只读取盲题包和知识点目录；答案键仅在评分阶段读取。",
        "- 本轮仍按模型分层判断：学段/年级/课次/模块/最小知识点 Top3。",
        "",
        "## 总体结果",
        "",
        "| 测试集 | 样本数 | 缺失预测 | 课次 Top3 | 模块 Top3 | 最小知识点 Top3 | 精确 knowledge_id Top3 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            "| {set_name} | {evaluated} | {missing_predictions} | {lesson} | {module} | {min_kp} | {kid} |".format(
                set_name=row["set_name"],
                evaluated=row["evaluated"],
                missing_predictions=row["missing_predictions"],
                lesson=pct(row["lesson_top3_hit_rate"]),
                module=pct(row["module_top3_hit_rate"]),
                min_kp=pct(row["min_kp_top3_hit_rate"]),
                kid=pct(row["knowledge_id_top3_hit_rate"]),
            )
        )

    lines.extend(
        [
            "",
            "## 年级分布结果",
            "",
            "| 测试集 | 年级组 | 样本数 | 课次 Top3 | 模块 Top3 | 最小知识点 Top3 |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in by_group:
        lines.append(
            "| {set_name} | {group} | {n} | {lesson} | {module} | {min_kp} |".format(
                set_name=row["set_name"],
                group=row["group"],
                n=row["n"],
                lesson=pct(row["lesson_top3_hit_rate"]),
                module=pct(row["module_top3_hit_rate"]),
                min_kp=pct(row["min_kp_top3_hit_rate"]),
            )
        )

    lines.extend(["", "## 问题类型", "", "| 问题类型 | 数量 |", "|---|---:|"])
    for issue_type, count in issue_counter.most_common():
        lines.append(f"| {issue_type} | {count} |")

    clean = next(s for s in summaries if s["set_name"] == "clean_30")
    expanded = next(s for s in summaries if s["set_name"] == "expanded_140")
    lines.extend(
        [
            "",
            "## 初步判断",
            "",
            f"- 干净金标 `clean_30` 的最小知识点 Top3 命中率为 {pct(clean['min_kp_top3_hit_rate'])}，这是当前更可信的模型能力观察值。",
            f"- 扩展集 `expanded_140` 的最小知识点 Top3 命中率为 {pct(expanded['min_kp_top3_hit_rate'])}。若低于干净集，主要看作暂用金标和裁切边界带来的噪声。",
            "- 如果课次命中明显高于最小知识点命中，说明大方向可用，但细点边界和题面质量还需要继续清洗。",
            "",
            "## 文件",
            "",
            "- `curated_min_kp_eval_v0.2.xlsx`：二轮评分表。",
            "- `curated_min_kp_eval_v0.2.json`：机器可读评分结果。",
            "- `predictions_expanded_chunk_01.json` 到 `predictions_expanded_chunk_04.json`：模型预测结果。",
        ]
    )

    (RUN / "curated_min_kp_eval_report_v0.2.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
