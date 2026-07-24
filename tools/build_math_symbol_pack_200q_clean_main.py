from __future__ import annotations

import csv
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
SRC_PACK = OUTPUTS / "math_symbol_image_pack_200q_20260624_production_curated"
DST_PACK = OUTPUTS / "math_symbol_image_pack_200q_20260624_clean_main"


def p(*parts: str) -> Path:
    return ROOT.joinpath(*parts)


REPLACEMENTS = {
    "case_089": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_sequence_arith_v02_20260624",
            "question_crops",
            "tq_001_考点1：等差数列的基本公式与性质_题目区回退_Q1.png",
        ),
        "slug": "sequence_arith_q1_curated",
        "source_run": "seed_senior_sequence_arith_v02_20260624",
        "source_ref": "tq_001_考点1：等差数列的基本公式与性质_题目区回退_Q1.png",
        "note_zh": "人工复核后保留的单题图，覆盖等差数列基础公式、下标与填空结构。",
    },
    "case_090": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_sequence_arith_v02_20260624",
            "question_crops",
            "tq_002_考点1：等差数列的基本公式与性质_题目区回退_Q2.png",
        ),
        "slug": "sequence_arith_q2_curated",
        "source_run": "seed_senior_sequence_arith_v02_20260624",
        "source_ref": "tq_002_考点1：等差数列的基本公式与性质_题目区回退_Q2.png",
        "note_zh": "人工复核后保留的单题图，覆盖求和表达与参数化等差数列。",
    },
    "case_091": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_sequence_arith_v02_20260624",
            "question_crops",
            "tq_006_考点1：等差数列的基本公式与性质_题目区回退_Q6.png",
        ),
        "slug": "sequence_arith_q6_curated",
        "source_run": "seed_senior_sequence_arith_v02_20260624",
        "source_ref": "tq_006_考点1：等差数列的基本公式与性质_题目区回退_Q6.png",
        "note_zh": "人工复核后替换为更干净的单题图，保留填空与数列不等式符号风险。",
    },
    "case_092": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_sequence_sumrec_v02_20260624",
            "question_crops",
            "tq_001_考点1：和与和的递推求通项_题目区回退_Q1.png",
        ),
        "slug": "sequence_sumsum_q1_curated",
        "source_run": "seed_senior_sequence_sumrec_v02_20260624",
        "source_ref": "tq_001_考点1：和与和的递推求通项_题目区回退_Q1.png",
        "note_zh": "人工复核后保留的单题图，覆盖 S_n 到 a_n 的递推展开与分段表达。",
    },
    "case_093": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_sequence_sumrec_v02_20260624",
            "question_crops",
            "tq_003_考点1：和与和的递推求通项_题目区回退_Q3.png",
        ),
        "slug": "sequence_sumsum_q3_curated",
        "source_run": "seed_senior_sequence_sumrec_v02_20260624",
        "source_ref": "tq_003_考点1：和与和的递推求通项_题目区回退_Q3.png",
        "note_zh": "人工复核后替换为更干净的递推题图，保留幂次与分段通项覆盖。",
    },
    "case_094": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_sequence_sumrec_v02_20260624",
            "question_crops",
            "tq_013_考点3：“特殊和”求通项_题目区回退_Q14.png",
        ),
        "slug": "sequence_specialsum_q14_curated",
        "source_run": "seed_senior_sequence_sumrec_v02_20260624",
        "source_ref": "tq_013_考点3：“特殊和”求通项_题目区回退_Q14.png",
        "note_zh": "人工复核后保留的特殊和求通项题图，覆盖加权和、阶乘与通项表达。",
    },
    "case_149": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_trig_identity_letters_20260624",
            "question_crops",
            "tq_001_考点1：单一角度化简求值_题目区回退_Q1.png",
        ),
        "slug": "trig_identity_q1_curated",
        "source_run": "seed_senior_trig_identity_letters_20260624",
        "source_ref": "tq_001_考点1：单一角度化简求值_题目区回退_Q1.png",
        "note_zh": "人工复核后保留的单题图，覆盖 tan(theta)、tan(theta+pi/4) 类公式转写风险。",
    },
    "case_150": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_trig_identity_letters_20260624",
            "question_crops",
            "tq_002_考点1：单一角度化简求值_题目区回退_Q2.png",
        ),
        "slug": "trig_identity_q2_trimmed",
        "source_run": "seed_senior_trig_identity_letters_20260624",
        "source_ref": "tq_002_考点1：单一角度化简求值_题目区回退_Q2.png",
        "crop": (0, 0, 680, 505),
        "note_zh": "人工裁掉了下一题起始片段，仅保留当前单题与答案解析。",
    },
    "case_151": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_trig_identity_letters_20260624",
            "question_crops",
            "tq_003_考点1：单一角度化简求值_题目区回退_Q3.png",
        ),
        "slug": "trig_identity_q3_curated",
        "source_run": "seed_senior_trig_identity_letters_20260624",
        "source_ref": "tq_003_考点1：单一角度化简求值_题目区回退_Q3.png",
        "note_zh": "人工复核后保留的单题图，覆盖 cos^2(alpha)+2sin2alpha 等组合表达。",
    },
    "case_152": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_trig_identity_letters_20260624",
            "question_crops",
            "tq_004_考点1：单一角度化简求值_题目区回退_Q4.png",
        ),
        "slug": "trig_identity_q4_curated",
        "source_run": "seed_senior_trig_identity_letters_20260624",
        "source_ref": "tq_004_考点1：单一角度化简求值_题目区回退_Q4.png",
        "note_zh": "人工复核后保留的单题图，覆盖 sin(theta)(1+sin2theta)/(sin(theta)+cos(theta)) 结构。",
    },
    "case_153": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_trig_identity_letters_20260624",
            "question_crops",
            "tq_005_考点1：单一角度化简求值_题目区回退_Q5.png",
        ),
        "slug": "trig_identity_q5_curated",
        "source_run": "seed_senior_trig_identity_letters_20260624",
        "source_ref": "tq_005_考点1：单一角度化简求值_题目区回退_Q5.png",
        "note_zh": "人工复核后保留同题跨页连续内容，不含跨题污染。",
    },
    "case_154": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_trig_identity_letters_20260624",
            "question_crops",
            "tq_006_考点1：单一角度化简求值_题目区回退_Q6.png",
        ),
        "slug": "trig_identity_q6_curated",
        "source_run": "seed_senior_trig_identity_letters_20260624",
        "source_ref": "tq_006_考点1：单一角度化简求值_题目区回退_Q6.png",
        "note_zh": "人工复核后保留的单题图，覆盖 tan2alpha 与分式恒等变换。",
    },
    "case_155": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_trig_identity_letters_20260624",
            "question_crops",
            "tq_007_考点2：多角度化简求值_题目区回退_Q7.png",
        ),
        "slug": "trig_identity_q7_curated",
        "source_run": "seed_senior_trig_identity_letters_20260624",
        "source_ref": "tq_007_考点2：多角度化简求值_题目区回退_Q7.png",
        "note_zh": "人工复核后保留同题跨页连续内容，覆盖 alpha、beta 与 cos((pi/4)-beta/2) 组合符号。",
    },
    "case_156": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_trig_identity_letters_20260624",
            "question_crops",
            "tq_008_考点2：多角度化简求值_题目区回退_Q8.png",
        ),
        "slug": "trig_identity_q8_curated",
        "source_run": "seed_senior_trig_identity_letters_20260624",
        "source_ref": "tq_008_考点2：多角度化简求值_题目区回退_Q8.png",
        "note_zh": "人工复核后保留的单题图，覆盖 tan(alpha+beta) 反推与字母角求值。",
    },
    "case_157": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_trig_identity_letters_20260624",
            "question_crops",
            "tq_009_考点2：多角度化简求值_题目区回退_Q9.png",
        ),
        "slug": "trig_identity_q9_curated",
        "source_run": "seed_senior_trig_identity_letters_20260624",
        "source_ref": "tq_009_考点2：多角度化简求值_题目区回退_Q9.png",
        "note_zh": "人工复核后保留同题跨页连续内容，覆盖 cos2alpha、tan(alpha-beta) 等多角表达。",
    },
    "case_158": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_trig_identity_letters_20260624",
            "question_crops",
            "tq_010_考点2：多角度化简求值_题目区回退_Q10.png",
        ),
        "slug": "trig_identity_q10_curated",
        "source_run": "seed_senior_trig_identity_letters_20260624",
        "source_ref": "tq_010_考点2：多角度化简求值_题目区回退_Q10.png",
        "note_zh": "人工复核后保留的单题图，覆盖 sin(x+y)、sin2x、sin2y 的联立化简。",
    },
    "case_159": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_ellipse_20260624",
            "question_crops",
            "tq_001_item_课后落实_Q1.png",
        ),
        "slug": "ellipse_q1_curated",
        "source_run": "seed_senior_ellipse_20260624",
        "source_ref": "tq_001_item_课后落实_Q1.png",
        "note_zh": "人工复核后保留的单题图，覆盖椭圆标准方程与焦点坐标。",
    },
    "case_160": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_ellipse_20260624",
            "question_crops",
            "tq_002_item_课后落实_Q2.png",
        ),
        "slug": "ellipse_q2_curated",
        "source_run": "seed_senior_ellipse_20260624",
        "source_ref": "tq_002_item_课后落实_Q2.png",
        "note_zh": "人工复核后保留的单题图，覆盖根式距离和转椭圆方程。",
    },
    "case_161": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_ellipse_20260624",
            "question_crops",
            "tq_003_item_课后落实_Q3.png",
        ),
        "slug": "ellipse_q3_curated",
        "source_run": "seed_senior_ellipse_20260624",
        "source_ref": "tq_003_item_课后落实_Q3.png",
        "note_zh": "人工复核后保留的单题图，覆盖 |AF1|+|AF2| 与几何量计算。",
    },
    "case_162": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_ellipse_20260624",
            "question_crops",
            "tq_004_item_课后落实_Q4.png",
        ),
        "slug": "ellipse_q4_curated",
        "source_run": "seed_senior_ellipse_20260624",
        "source_ref": "tq_004_item_课后落实_Q4.png",
        "note_zh": "人工复核后保留同题跨页连续内容，覆盖点 P 坐标与面积计算。",
    },
    "case_163": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_ellipse_20260624",
            "question_crops",
            "tq_005_item_课后落实_Q5.png",
        ),
        "slug": "ellipse_q5_curated",
        "source_run": "seed_senior_ellipse_20260624",
        "source_ref": "tq_005_item_课后落实_Q5.png",
        "note_zh": "人工复核后保留的单题图，覆盖离心率与角度条件。",
    },
    "case_164": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_ellipse_20260624",
            "question_crops",
            "tq_006_item_课后落实_Q6.png",
        ),
        "slug": "ellipse_q6_curated",
        "source_run": "seed_senior_ellipse_20260624",
        "source_ref": "tq_006_item_课后落实_Q6.png",
        "note_zh": "人工复核后保留同题跨页连续内容，覆盖离心率、斜率与向量型推导。",
    },
    "case_165": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_ellipse_20260624",
            "question_crops",
            "tq_007_item_课后落实_Q7.png",
        ),
        "slug": "ellipse_q7_curated",
        "source_run": "seed_senior_ellipse_20260624",
        "source_ref": "tq_007_item_课后落实_Q7.png",
        "note_zh": "人工复核后保留的单题图，覆盖椭圆与三角形周长、坐标几何混合表达。",
    },
    "case_166": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_ellipse_20260624",
            "question_crops",
            "tq_008_item_课后落实_Q8.png",
        ),
        "slug": "ellipse_q8_curated",
        "source_run": "seed_senior_ellipse_20260624",
        "source_ref": "tq_008_item_课后落实_Q8.png",
        "note_zh": "人工复核后保留同题跨页连续内容，覆盖同焦点、过定点与待定系数设方程。",
    },
    "case_167": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_hyperbola_20260624",
            "question_crops",
            "tq_001_item_课后落实_Q1.png",
        ),
        "slug": "hyperbola_q1_trimmed",
        "source_run": "seed_senior_hyperbola_20260624",
        "source_ref": "tq_001_item_课后落实_Q1.png",
        "crop": (0, 0, 680, 468),
        "note_zh": "人工裁掉了下一题起始片段，仅保留当前单题与答案解析。",
    },
    "case_168": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_hyperbola_20260624",
            "question_crops",
            "tq_002_item_课后落实_Q2.png",
        ),
        "slug": "hyperbola_q2_curated",
        "source_run": "seed_senior_hyperbola_20260624",
        "source_ref": "tq_002_item_课后落实_Q2.png",
        "note_zh": "人工复核后保留的单题图，覆盖参数范围与双曲线轴向判断。",
    },
    "case_169": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_hyperbola_20260624",
            "question_crops",
            "tq_003_item_课后落实_Q3.png",
        ),
        "slug": "hyperbola_q3_curated",
        "source_run": "seed_senior_hyperbola_20260624",
        "source_ref": "tq_003_item_课后落实_Q3.png",
        "note_zh": "人工复核后保留的单题图，覆盖 m 参双曲线、定义域与并集表达。",
    },
    "case_170": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_hyperbola_20260624",
            "question_crops",
            "tq_004_item_课后落实_Q4.png",
        ),
        "slug": "hyperbola_q4_curated",
        "source_run": "seed_senior_hyperbola_20260624",
        "source_ref": "tq_004_item_课后落实_Q4.png",
        "note_zh": "人工复核后保留同题跨页连续内容，覆盖 x^2+my^2=1 与参数求值。",
    },
    "case_171": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_hyperbola_20260624",
            "question_crops",
            "tq_005_item_课后落实_Q5.png",
        ),
        "slug": "hyperbola_q5_curated",
        "source_run": "seed_senior_hyperbola_20260624",
        "source_ref": "tq_005_item_课后落实_Q5.png",
        "note_zh": "人工复核后保留的单题图，覆盖渐近线方程与参数反求。",
    },
    "case_172": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_hyperbola_20260624",
            "question_crops",
            "tq_006_item_课后落实_Q6.png",
        ),
        "slug": "hyperbola_q6_curated",
        "source_run": "seed_senior_hyperbola_20260624",
        "source_ref": "tq_006_item_课后落实_Q6.png",
        "note_zh": "人工复核后保留同题跨页连续内容，覆盖焦点到渐近线距离与倾斜角。",
    },
    "case_173": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_hyperbola_20260624",
            "question_crops",
            "tq_007_item_课后落实_Q7.png",
        ),
        "slug": "hyperbola_q7_trimmed",
        "source_run": "seed_senior_hyperbola_20260624",
        "source_ref": "tq_007_item_课后落实_Q7.png",
        "crop": (0, 0, 680, 760),
        "note_zh": "人工裁掉了下一题起始片段，仅保留当前单题与配图解析。",
    },
    "case_174": {
        "source": p(
            "outputs",
            "ingress_splitter_v0.1",
            "seed_senior_hyperbola_20260624",
            "question_crops",
            "tq_008_item_课后落实_Q8.png",
        ),
        "slug": "hyperbola_q8_curated",
        "source_run": "seed_senior_hyperbola_20260624",
        "source_ref": "tq_008_item_课后落实_Q8.png",
        "note_zh": "人工复核后保留的单题图，覆盖离心率范围与渐近线夹角。",
    },
}


AUDIT_MODULES = {
    "07_trigonometry",
    "08_analytic_geometry",
    "11_sequences",
}


def ensure_generated_target(dst: Path) -> None:
    if OUTPUTS not in dst.parents:
        raise RuntimeError(f"Refusing to write outside outputs: {dst}")


def read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(csv_path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0].keys())
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def to_bool(value: str) -> bool:
    return str(value).strip().lower() == "true"


def crop_image_if_needed(img: Image.Image, spec: dict) -> Image.Image:
    if "crop" not in spec:
        return img
    left, top, right, bottom = spec["crop"]
    return img.crop((left, top, right, bottom))


def save_replacement_image(spec: dict, target_path: Path) -> None:
    with Image.open(spec["source"]) as img:
        cleaned = crop_image_if_needed(img, spec)
        cleaned.save(target_path)


def update_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, str]]:
    by_case = {row["case_id"]: row for row in rows}
    old_paths: dict[str, str] = {}

    for case_id, spec in REPLACEMENTS.items():
        if case_id not in by_case:
            raise KeyError(f"Missing case in manifest: {case_id}")
        if not spec["source"].exists():
            raise FileNotFoundError(spec["source"])

        row = by_case[case_id]
        old_paths[case_id] = row["packaged_image"]

        module_dir = f"{row['module_en']}__{row['module_zh']}"
        new_rel = f"images/{module_dir}/{case_id}__{spec['slug']}.png"
        row["source_type"] = "manual_curated_clean_main"
        row["source_run"] = spec["source_run"]
        row["source_ref"] = spec["source_ref"]
        row["component_label"] = "人工精选"
        row["needs_human_review"] = "False"
        row["packaged_image"] = new_rel
        row["note_zh"] = spec["note_zh"]
        row["audit_status"] = "manual_clean_main_2026_06_24"

    return rows, old_paths


def json_ready_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    cooked: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        item["needs_human_review"] = to_bool(row["needs_human_review"])
        cooked.append(item)
    return cooked


def write_manifest_json(json_path: Path, rows: list[dict[str, str]]) -> None:
    module_counts_en = Counter(row["module_en"] for row in rows)
    module_counts_zh = Counter(row["module_zh"] for row in rows)
    payload = {
        "package_name": DST_PACK.name,
        "case_count": len(rows),
        "module_counts_en": dict(sorted(module_counts_en.items())),
        "module_counts_zh": dict(sorted(module_counts_zh.items())),
        "notes": [
            "基于 production_curated 备份重建的 clean main 主包。",
            "清洗了 32 张边界样本：保留同题跨页连续，裁掉跨题污染，去除回退类脏标签。",
            "manifest.json 为本次重建后的有效 UTF-8 JSON，可直接被 JSON 解析器读取。",
        ],
        "cases": json_ready_rows(rows),
    }
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def write_readme(readme_path: Path, rows: list[dict[str, str]]) -> None:
    module_counts_en = Counter(row["module_en"] for row in rows)
    module_counts_zh = {
        module_en: next(row["module_zh"] for row in rows if row["module_en"] == module_en)
        for module_en in module_counts_en
    }
    cleaned_cases = sorted(REPLACEMENTS)
    cleaned_summary = ", ".join(cleaned_cases[:6]) + f" ... 共 {len(cleaned_cases)} 题"

    lines = [
        "# 数学符号测试图包：200题 clean main 主包",
        "",
        f"- 包名：`{DST_PACK.name}`",
        f"- 总题量：`{len(rows)}`",
        "- 定位：用于视觉拆解、题图转录、公式符号回归的主测试包。",
        "- 特点：保留同题跨页连续内容，清除跨题污染，重写有效 JSON 清单。",
        f"- 本次清洗范围：`{cleaned_summary}`",
        "",
        "## 模块分布",
        "",
        "| English | 中文 | 数量 |",
        "|---|---|---:|",
    ]
    for module_en in sorted(module_counts_en):
        lines.append(
            f"| `{module_en}` | {module_counts_zh[module_en]} | {module_counts_en[module_en]} |"
        )

    lines.extend(
        [
            "",
            "## 主要文件",
            "",
            "- `manifest.json`：有效 UTF-8 JSON 清单。",
            "- `manifest.csv`：便于筛选和统计。",
            "- `images/`：按模块分目录存放的题图。",
            "- `_module_audit_sheets/`：模块级缩略图总览。",
            "",
            "## 清洗规则",
            "",
            "- 同题跨页连续内容保留，不算污染。",
            "- 下一题开头、知识点页块、误吸入页头页尾会被裁掉或替换。",
            "- 原始来源仍保留在 `source_ref` 中，便于回溯。",
        ]
    )

    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_thumb(img_path: Path, cell_size: tuple[int, int]) -> Image.Image:
    with Image.open(img_path) as img:
        thumb = ImageOps.contain(img.convert("RGB"), cell_size)
    canvas = Image.new("RGB", cell_size, "white")
    x = (cell_size[0] - thumb.width) // 2
    y = (cell_size[1] - thumb.height) // 2
    canvas.paste(thumb, (x, y))
    return canvas


def rebuild_module_audit_sheets(rows: list[dict[str, str]]) -> None:
    audit_dir = DST_PACK / "_module_audit_sheets"
    audit_dir.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["module_en"] in AUDIT_MODULES:
            grouped[row["module_en"]].append(row)

    cell_w, cell_h = 220, 220
    cols = 4
    gap = 12
    margin = 16

    for module_en, module_rows in grouped.items():
        module_rows = sorted(module_rows, key=lambda r: r["case_id"])
        thumbs = [make_thumb(DST_PACK / row["packaged_image"], (cell_w, cell_h)) for row in module_rows]
        rows_needed = (len(thumbs) + cols - 1) // cols
        sheet_w = margin * 2 + cols * cell_w + (cols - 1) * gap
        sheet_h = margin * 2 + rows_needed * cell_h + (rows_needed - 1) * gap
        sheet = Image.new("RGB", (sheet_w, sheet_h), "white")
        for idx, thumb in enumerate(thumbs):
            r = idx // cols
            c = idx % cols
            x = margin + c * (cell_w + gap)
            y = margin + r * (cell_h + gap)
            sheet.paste(thumb, (x, y))
        sheet.save(audit_dir / f"{module_en}.png")


def zip_dir(src_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zf:
        for path in sorted(src_dir.rglob("*")):
            if path == zip_path:
                continue
            zf.write(path, path.relative_to(src_dir.parent))


def build() -> None:
    ensure_generated_target(DST_PACK)
    if DST_PACK.exists():
        shutil.rmtree(DST_PACK)
    shutil.copytree(SRC_PACK, DST_PACK)

    rows = read_rows(SRC_PACK / "manifest.csv")
    rows, old_paths = update_rows(rows)

    for case_id, spec in REPLACEMENTS.items():
        row = next(row for row in rows if row["case_id"] == case_id)
        old_rel = old_paths[case_id]
        old_abs = DST_PACK / old_rel
        new_abs = DST_PACK / row["packaged_image"]
        new_abs.parent.mkdir(parents=True, exist_ok=True)
        save_replacement_image(spec, new_abs)
        if old_abs.exists() and old_abs != new_abs:
            old_abs.unlink()

    write_rows(DST_PACK / "manifest.csv", rows)
    write_manifest_json(DST_PACK / "manifest.json", rows)
    write_readme(DST_PACK / "README.md", rows)
    rebuild_module_audit_sheets(rows)
    zip_dir(DST_PACK, DST_PACK.with_suffix(".zip"))


if __name__ == "__main__":
    build()
