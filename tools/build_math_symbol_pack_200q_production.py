from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
SRC_PACK = OUTPUTS / "math_symbol_image_pack_100q_20260624_bilingual_curated"
DST_PACK = OUTPUTS / "math_symbol_image_pack_200q_20260624_production_curated"


MODULE_ZH = {
    "01_basic_numbers": "基础数与式",
    "02_equation_inequality": "方程与不等式",
    "03_junior_functions": "初中函数",
    "04_plane_geometry": "平面几何",
    "05_sets_logic": "集合与逻辑",
    "06_senior_functions": "高中函数",
    "07_trigonometry": "三角函数",
    "08_analytic_geometry": "解析几何",
    "09_solid_geometry_vectors": "立体几何与向量",
    "10_derivative_complex": "导数与复数",
    "11_sequences": "数列",
    "12_probability_statistics": "概率统计",
}


EXTRA_GROUPS = [
    {
        "module_en": "01_basic_numbers",
        "submodule_en": "monomial-polynomial-parameters",
        "submodule_zh": "整式概念与参数",
        "source_run": "seed_junior_poly_20260624",
        "tags_en": ["expression", "monomial", "polynomial", "parameter"],
        "tags_zh": ["数与式", "单项式", "多项式", "参数"],
        "note_zh": "补入整式与参数题，增强字母、次数、系数、整式结构的覆盖。",
        "filenames": [
            "tq_001_考点1_单项式的概念_例题讲解_Q例1.png",
            "tq_004_考点2_单项式的系数与次数_例题讲解_Q例2.png",
            "tq_009_考点3_单项式概念求解参数的值_例题讲解_Q例4.png",
            "tq_016_考点1_多项式的概念_例题讲解_Q例6.png",
            "tq_017_考点2_多项式的项数与次数_例题讲解_Q例7.png",
            "tq_023_考点3_多项式概念求解参数的值_例题讲解_Q例9.png",
        ],
    },
    {
        "module_en": "03_junior_functions",
        "submodule_en": "inverse-proportion-comprehensive",
        "submodule_zh": "反比例函数综合",
        "source_run": "seed_junior_inverse_function_20260624",
        "tags_en": ["junior-function", "inverse-proportion", "geometry", "coordinate"],
        "tags_zh": ["初中函数", "反比例函数", "几何综合", "坐标系"],
        "note_zh": "补入反比例函数与线段、三角形、四边形的综合题。",
        "filenames": [
            "tq_002_考点1_反比例函数中的线段问题_例题讲解_Q例1.png",
            "tq_003_考点1_反比例函数中的线段问题_例题讲解_Q例2.png",
            "tq_005_考点1_反比例函数与三角形_例题讲解_Q例3.png",
            "tq_006_考点1_反比例函数与三角形_例题讲解_Q例4.png",
            "tq_007_考点1_反比例函数与三角形_例题讲解_Q例5.png",
            "tq_009_考点2_反比例函数与四边形_例题讲解_Q例7.png",
            "tq_010_考点2_反比例函数与四边形_例题讲解_Q例8.png",
            "tq_011_考点2_反比例函数与四边形_例题讲解_Q例9.png",
            "tq_013_考点2_反比例函数与四边形_课后落实_Q课后1.png",
            "tq_015_考点2_反比例函数与四边形_课后落实_Q课后3.png",
        ],
    },
    {
        "module_en": "04_plane_geometry",
        "submodule_en": "circle-proof-and-calculation",
        "submodule_zh": "圆中的证明与计算",
        "source_run": "seed_junior_circle_proofcalc_20260624",
        "tags_en": ["plane-geometry", "circle", "tangent", "incircle"],
        "tags_zh": ["平面几何", "圆", "切线", "内切圆"],
        "note_zh": "补入初中圆专题，覆盖切线判定、切线长定理、三角形内切圆。",
        "filenames": [
            "tq_001_考点1_切线的判定与性质_例题讲解_Q例1.png",
            "tq_002_考点1_切线的判定与性质_例题讲解_Q例2.png",
            "tq_003_考点1_切线的判定与性质_例题讲解_Q例3.png",
            "tq_004_考点1_切线的判定与性质_例题讲解_Q例4.png",
            "tq_005_考点2_切线长定理_例题讲解_Q例5.png",
            "tq_006_考点2_切线长定理_例题讲解_Q例6.png",
            "tq_007_考点2_切线长定理_例题讲解_Q例7.png",
            "tq_008_考点2_切线长定理_例题讲解_Q例8.png",
            "tq_009_考点3_三角形内切圆_例题讲解_Q例9.png",
            "tq_010_考点3_三角形内切圆_例题讲解_Q例10.png",
        ],
    },
    {
        "module_en": "04_plane_geometry",
        "submodule_en": "folding-transformations",
        "submodule_zh": "几何变换之折叠",
        "source_run": "seed_junior_fold_20260624",
        "tags_en": ["plane-geometry", "folding", "transformation", "proof"],
        "tags_zh": ["平面几何", "折叠", "几何变换", "证明"],
        "note_zh": "补入折叠类几何题，增强图形归属、辅助线和变换后的符号覆盖。",
        "filenames": [
            "tq_001_考点1_矩形折叠问题_例题讲解_Q例1.png",
            "tq_002_考点1_矩形折叠问题_强化训练_Q变式1-1.png",
            "tq_004_考点1_矩形折叠问题_例题讲解_Q例2.png",
            "tq_008_考点2_正方形折叠问题_例题讲解_Q例4.png",
            "tq_010_考点2_正方形折叠问题_例题讲解_Q例5.png",
            "tq_011_考点2_正方形折叠问题_强化训练_Q变式5-1.png",
            "tq_013_考点2_正方形折叠问题_例题讲解_Q例6.png",
            "tq_016_考点3_其他折叠问题_例题讲解_Q例7.png",
            "tq_017_考点3_其他折叠问题_例题讲解_Q例8.png",
            "tq_023_考点3_其他折叠问题_课后落实_Q课后1.png",
        ],
    },
    {
        "module_en": "06_senior_functions",
        "submodule_en": "elementary-functions-exp-log-power",
        "submodule_zh": "指对幂函数",
        "source_run": "seed_senior_elementary_functions_20260624",
        "tags_en": ["function", "exponential", "logarithm", "power-function"],
        "tags_zh": ["高中函数", "指数函数", "对数函数", "幂函数"],
        "note_zh": "补入指对幂运算、图象性质和比大小问题。",
        "filenames": [
            "tq_001_考点1：指对幂运算_例题讲解_Q1.png",
            "tq_003_考点1：指对幂运算_例题讲解_Q3.png",
            "tq_005_考点1：指对幂运算_强化训练_Q5.png",
            "tq_010_考点2：指对幂函数图象及性质_例题讲解_Q1.png",
            "tq_012_考点2：指对幂函数图象及性质_例题讲解_Q3.png",
            "tq_015_考点2：指对幂函数图象及性质_例题讲解_Q6.png",
            "tq_018_考点2：指对幂函数图象及性质_例题讲解_Q9.png",
            "tq_026_考点3：指对幂比大小_例题讲解_Q1.png",
            "tq_029_考点3：指对幂比大小_例题讲解_Q2.png",
            "tq_031_考点3：指对幂比大小_例题讲解_Q4.png",
            "tq_038_考点3：指对幂比大小_强化训练_Q8.png",
            "tq_057_考点3：指对幂比大小_课后落实_Q1.png",
        ],
    },
    {
        "module_en": "07_trigonometry",
        "submodule_en": "trig-identity-letter-angle",
        "submodule_zh": "三角恒等变换",
        "source_run": "seed_senior_trig_identity_letters_20260624",
        "tags_en": ["trigonometry", "identity", "tan", "angle-transform"],
        "tags_zh": ["三角函数", "恒等变换", "正切", "角度化简"],
        "note_zh": "补入单一角和多角度化简求值题，增强三角公式转写风险覆盖。",
        "filenames": [
            "tq_001_考点1：单一角度化简求值_题目区回退_Q1.png",
            "tq_002_考点1：单一角度化简求值_题目区回退_Q2.png",
            "tq_003_考点1：单一角度化简求值_题目区回退_Q3.png",
            "tq_004_考点1：单一角度化简求值_题目区回退_Q4.png",
            "tq_005_考点1：单一角度化简求值_题目区回退_Q5.png",
            "tq_006_考点1：单一角度化简求值_题目区回退_Q6.png",
            "tq_007_考点2：多角度化简求值_题目区回退_Q7.png",
            "tq_008_考点2：多角度化简求值_题目区回退_Q8.png",
            "tq_009_考点2：多角度化简求值_题目区回退_Q9.png",
            "tq_010_考点2：多角度化简求值_题目区回退_Q10.png",
        ],
    },
    {
        "module_en": "08_analytic_geometry",
        "submodule_en": "ellipse-properties",
        "submodule_zh": "椭圆方程及其性质",
        "source_run": "seed_senior_ellipse_20260624",
        "tags_en": ["analytic-geometry", "ellipse", "standard-form", "parameter"],
        "tags_zh": ["解析几何", "椭圆", "标准方程", "参数"],
        "note_zh": "补入椭圆专题，增强焦点、离心率、标准方程等符号覆盖。",
        "filenames": [
            "tq_001_item_课后落实_Q1.png",
            "tq_002_item_课后落实_Q2.png",
            "tq_003_item_课后落实_Q3.png",
            "tq_004_item_课后落实_Q4.png",
            "tq_005_item_课后落实_Q5.png",
            "tq_006_item_课后落实_Q6.png",
            "tq_007_item_课后落实_Q7.png",
            "tq_008_item_课后落实_Q8.png",
        ],
    },
    {
        "module_en": "08_analytic_geometry",
        "submodule_en": "hyperbola-properties",
        "submodule_zh": "双曲线及其性质",
        "source_run": "seed_senior_hyperbola_20260624",
        "tags_en": ["analytic-geometry", "hyperbola", "asymptote", "parameter"],
        "tags_zh": ["解析几何", "双曲线", "渐近线", "参数"],
        "note_zh": "补入双曲线专题，增强渐近线、离心率和参数范围类表达。",
        "filenames": [
            "tq_001_item_课后落实_Q1.png",
            "tq_002_item_课后落实_Q2.png",
            "tq_003_item_课后落实_Q3.png",
            "tq_004_item_课后落实_Q4.png",
            "tq_005_item_课后落实_Q5.png",
            "tq_006_item_课后落实_Q6.png",
            "tq_007_item_课后落实_Q7.png",
            "tq_008_item_课后落实_Q8.png",
        ],
    },
    {
        "module_en": "09_solid_geometry_vectors",
        "submodule_en": "space-vectors",
        "submodule_zh": "空间向量及其运算",
        "source_run": "seed_senior_space_vector_20260624",
        "tags_en": ["solid-geometry", "vector", "dot-product", "projection"],
        "tags_zh": ["立体几何", "向量", "数量积", "投影向量"],
        "note_zh": "补入空间向量概念、数量积和投影向量题。",
        "filenames": [
            "tq_001_考点1：空间向量的概念_例题讲解_Q1.png",
            "tq_003_考点1：空间向量的概念_例题讲解_Q3.png",
            "tq_004_考点2：空间向量的加减运算_强化训练_Q1.png",
            "tq_007_考点2：空间向量的加减运算_强化训练_Q4.png",
            "tq_013_考点1：数量积的计算_例题讲解_Q1.png",
            "tq_015_考点1：数量积的计算_例题讲解_Q3.png",
            "tq_017_考点1：数量积的计算_强化训练_Q5.png",
            "tq_022_考点2：投影向量_例题讲解_Q1.png",
            "tq_023_考点2：投影向量_例题讲解_Q2.png",
            "tq_024_考点2：投影向量_强化训练_Q3.png",
            "tq_027_考点2：投影向量_课后落实_Q1.png",
            "tq_029_考点2：投影向量_课后落实_Q3.png",
        ],
    },
    {
        "module_en": "10_derivative_complex",
        "submodule_en": "complex-number-specials",
        "submodule_zh": "复数专题",
        "source_run": "seed_senior_set_complex_20260624",
        "tags_en": ["complex", "modulus", "imaginary-unit", "geometry"],
        "tags_zh": ["复数", "模", "虚数单位", "几何意义"],
        "note_zh": "补入复数运算、几何意义和复数的模。",
        "filenames": [
            "tq_029_考点1：复数的定义和运算_例题讲解_Q1.png",
            "tq_030_考点1：复数的定义和运算_例题讲解_Q2.png",
            "tq_032_考点1：复数的定义和运算_强化训练_Q4.png",
            "tq_033_考点1：复数的定义和运算_强化训练_Q5.png",
            "tq_035_考点2：复数的几何意义_例题讲解_Q1.png",
            "tq_038_考点2：复数的几何意义_强化训练_Q4.png",
            "tq_041_考点3：复数的模_例题讲解_Q1.png",
            "tq_044_考点3：复数的模_强化训练_Q4.png",
        ],
    },
    {
        "module_en": "12_probability_statistics",
        "submodule_en": "probability-extra-samples",
        "submodule_zh": "概率统计补充题",
        "source_run": "seed_senior_probability_conditional_v01_20260624",
        "tags_en": ["probability", "conditional-probability", "independence", "counting"],
        "tags_zh": ["概率统计", "条件概率", "独立性", "计数原理"],
        "note_zh": "补入古典概型、条件概率、全概率和独立性补充题。",
        "filenames": [
            "tq_002_考点1：利用排列组合计算古典概型的相关问题_例题讲解_Q2.png",
            "tq_006_考点1：利用排列组合计算古典概型的相关问题_强化训练_Q6.png",
            "tq_012_考点2：概率的乘法原理_例题讲解_Q2.png",
            "tq_018_考点3：条件概率公式的概念与应用_例题讲解_Q2.png",
            "tq_031_考点4：全概率公式_强化训练_Q4.png",
            "tq_041_考点5：事件的独立性_强化训练_Q4.png",
        ],
    },
]


BASE_REPLACEMENTS = {
    "case_041": {
        "module_en": "04_plane_geometry",
        "submodule_en": "circle-proof-and-calculation",
        "submodule_zh": "圆中的证明与计算",
        "source_run": "seed_junior_circle_proofcalc_20260624",
        "source_ref": "tq_011_考点3_三角形内切圆_例题讲解_Q例11.png",
        "tags_en": ["plane-geometry", "circle", "tangent", "incircle"],
        "tags_zh": ["平面几何", "圆", "切线", "内切圆"],
        "note_zh": "替换原始文件名带 Q0 的几何题，避免压测包中残留 Q0 标记。",
    }
}


def infer_component_label(filename: str) -> str:
    if "例题讲解" in filename:
        return "例题讲解"
    if "强化训练" in filename:
        return "强化训练"
    if "课后落实" in filename:
        return "课后落实"
    if "题目区回退" in filename:
        return "题目区回退"
    return ""


def build_readme(module_counts: dict[str, int]) -> str:
    lines = [
        "# 数学符号测试图包（200题生产压测版）",
        "",
        f"- 包名：`{DST_PACK.name}`",
        "- 总题量：`200`",
        "- 版本定位：面向视觉转录与结构归属的生产前压测包",
        "- 构成：`100` 题来自已人工清洗包，`100` 题为本次补齐的高风险题型",
        "- 本次重点补齐：圆、反比例、折叠、指对幂函数、三角恒等变换、空间向量、椭圆、双曲线、复数、概率补充题",
        "",
        "## 模块分布",
        "",
        "| English | 中文 | 数量 |",
        "|---|---|---:|",
    ]
    for key in MODULE_ZH:
        lines.append(f"| `{key}` | {MODULE_ZH[key]} | {module_counts.get(key, 0)} |")
    lines.extend(
        [
            "",
            "## 主要文件",
            "",
            "- `manifest.json`：完整双语清单",
            "- `manifest.csv`：便于筛选和统计",
            "- `images/`：按模块分目录存放的题图",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    if DST_PACK.exists():
        shutil.rmtree(DST_PACK)
    (DST_PACK / "images").mkdir(parents=True, exist_ok=True)

    src_manifest = json.loads((SRC_PACK / "manifest.json").read_text(encoding="utf-8"))
    cases: list[dict] = []

    for case in src_manifest["cases"]:
        rel = Path(case["packaged_image"])
        src = SRC_PACK / rel
        module_dir = DST_PACK / rel.parent
        module_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, DST_PACK / rel)
        cloned = dict(case)
        cloned["audit_status"] = case.get("audit_status", "manually_checked_2026_06_24")
        cases.append(cloned)

    for case in cases:
        repl = BASE_REPLACEMENTS.get(case["case_id"])
        if not repl:
            continue
        old_rel = Path(case["packaged_image"])
        old_abs = DST_PACK / old_rel
        if old_abs.exists():
            old_abs.unlink()
        new_name = f"{case['case_id']}__{repl['source_ref']}"
        new_rel = old_rel.parent / new_name
        src = OUTPUTS / "ingress_splitter_v0.1" / repl["source_run"] / "question_crops" / repl["source_ref"]
        shutil.copy2(src, DST_PACK / new_rel)
        case["submodule_en"] = repl["submodule_en"]
        case["submodule_zh"] = repl["submodule_zh"]
        case["tags_en"] = repl["tags_en"]
        case["tags_zh"] = repl["tags_zh"]
        case["source_type"] = "manual_replacement_after_audit"
        case["source_run"] = repl["source_run"]
        case["source_ref"] = repl["source_ref"]
        case["packaged_image"] = new_rel.as_posix()
        case["component_label"] = infer_component_label(repl["source_ref"])
        case["note_zh"] = repl["note_zh"]
        case["needs_human_review"] = False
        case["audit_status"] = "replaced_q0_name_for_production_pack_2026_06_24"

    next_case_no = len(cases) + 1

    for group in EXTRA_GROUPS:
        target_dir = DST_PACK / "images" / f"{group['module_en']}__{MODULE_ZH[group['module_en']]}"
        target_dir.mkdir(parents=True, exist_ok=True)
        src_dir = OUTPUTS / "ingress_splitter_v0.1" / group["source_run"] / "question_crops"

        for filename in group["filenames"]:
            src = src_dir / filename
            if not src.exists():
                raise FileNotFoundError(src)
            case_id = f"case_{next_case_no:03d}"
            dst_name = f"{case_id}__{filename}"
            dst_rel = Path("images") / target_dir.name / dst_name
            shutil.copy2(src, DST_PACK / dst_rel)
            cases.append(
                {
                    "case_id": case_id,
                    "module_en": group["module_en"],
                    "module_zh": MODULE_ZH[group["module_en"]],
                    "submodule_en": group["submodule_en"],
                    "submodule_zh": group["submodule_zh"],
                    "tags_en": list(group["tags_en"]),
                    "tags_zh": list(group["tags_zh"]),
                    "source_type": "production_expansion_case",
                    "source_run": group["source_run"],
                    "source_ref": filename,
                    "packaged_image": dst_rel.as_posix(),
                    "component_label": infer_component_label(filename),
                    "note_zh": group["note_zh"],
                    "needs_human_review": False,
                    "audit_status": "selected_for_production_pack_2026_06_24",
                }
            )
            next_case_no += 1

    if len(cases) != 200:
        raise RuntimeError(f"Expected 200 cases, got {len(cases)}")

    module_counts_en = dict(Counter(case["module_en"] for case in cases))
    module_counts_zh = dict(Counter(case["module_zh"] for case in cases))

    manifest = {
        "package_name": DST_PACK.name,
        "case_count": len(cases),
        "module_counts_en": module_counts_en,
        "module_counts_zh": module_counts_zh,
        "notes": [
            "前100题沿用已人工清洗的100题双语包。",
            "后100题为本次针对高风险符号和题型补齐的生产压测样本。",
            "本版优先覆盖视觉转录最容易出错的图形归属、复杂公式、几何符号、函数与解析几何表达。",
        ],
        "cases": cases,
    }

    (DST_PACK / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    fieldnames = [
        "case_id",
        "module_en",
        "module_zh",
        "submodule_en",
        "submodule_zh",
        "source_type",
        "source_run",
        "source_ref",
        "component_label",
        "tags_en",
        "tags_zh",
        "needs_human_review",
        "packaged_image",
        "note_zh",
        "audit_status",
    ]
    with (DST_PACK / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in cases:
            out = dict(row)
            out["tags_en"] = ";".join(out.get("tags_en", []))
            out["tags_zh"] = ";".join(out.get("tags_zh", []))
            writer.writerow({k: out.get(k, "") for k in fieldnames})

    (DST_PACK / "README.md").write_text(build_readme(module_counts_en), encoding="utf-8")

    zip_path = OUTPUTS / f"{DST_PACK.name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zf:
        for path in sorted(DST_PACK.rglob("*")):
            zf.write(path, path.relative_to(DST_PACK.parent))

    print(
        json.dumps(
            {
                "out_dir": str(DST_PACK),
                "zip": str(zip_path),
                "case_count": len(cases),
                "module_counts_en": module_counts_en,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
