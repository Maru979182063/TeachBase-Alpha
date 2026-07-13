from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
SRC_PACK = OUTPUTS / "math_symbol_image_pack_100q_20260624_bilingual"
DST_PACK = OUTPUTS / "math_symbol_image_pack_100q_20260624_bilingual_curated"


REPLACEMENTS = {
    "case_012": {
        "src_run": "seed_junior_scinote_20260624",
        "src_name": "tq_004_考点1_科学记数法_例题讲解_Q10.png",
        "submodule_en": "scientific-notation",
        "submodule_zh": "科学记数法",
        "tags_en": ["number", "scientific-notation", "multiple-choice", "word-problem"],
        "tags_zh": ["数与式", "科学记数法", "选择题", "应用题"],
        "component_label": "例题讲解",
        "note_zh": "人工审核后替换了原来的能力进阶标题残片。",
    },
    "case_013": {
        "src_run": "seed_junior_scinote_20260624",
        "src_name": "tq_007_考点1_科学记数法_例题讲解_Q例4.png",
        "submodule_en": "scientific-notation",
        "submodule_zh": "科学记数法",
        "tags_en": ["number", "scientific-notation", "measurement", "word-problem"],
        "tags_zh": ["数与式", "科学记数法", "测量", "应用题"],
        "component_label": "例题讲解",
        "note_zh": "人工审核后替换了原来的单行残片。",
    },
    "case_017": {
        "src_run": "rerun_junior_g7_eq_to_equation_v02_20260624",
        "src_name": "tq_001_考点1_方程的定义_例题讲解_Q例1.png",
        "submodule_en": "equation-definition",
        "submodule_zh": "方程的定义",
        "tags_en": ["equation", "definition", "multiple-choice", "algebra"],
        "tags_zh": ["方程与不等式", "方程定义", "选择题", "代数"],
        "component_label": "例题讲解",
        "note_zh": "人工审核后替换了原来的知识导入页。",
    },
    "case_018": {
        "src_run": "rerun_junior_g7_eq_to_equation_v02_20260624",
        "src_name": "tq_002_考点1_方程的定义_强化训练_Q变式1-1.png",
        "submodule_en": "equation-definition",
        "submodule_zh": "方程的定义",
        "tags_en": ["equation", "definition", "drill", "algebra"],
        "tags_zh": ["方程与不等式", "方程定义", "强化训练", "代数"],
        "component_label": "强化训练",
        "note_zh": "人工审核后替换了原来的知识条目残片。",
    },
    "case_019": {
        "src_run": "rerun_junior_g7_eq_to_equation_v02_20260624",
        "src_name": "tq_003_考点1_方程的定义_强化训练_Q变式1-2.png",
        "submodule_en": "equation-definition",
        "submodule_zh": "方程的定义",
        "tags_en": ["equation", "definition", "drill", "basic-concept"],
        "tags_zh": ["方程与不等式", "方程定义", "强化训练", "基础概念"],
        "component_label": "强化训练",
        "note_zh": "人工审核后替换了原来的概念条目残片。",
    },
    "case_020": {
        "src_run": "rerun_junior_g7_eq_to_equation_v02_20260624",
        "src_name": "tq_005_考点2_方程的解_例题讲解_Q例2.png",
        "submodule_en": "equation-solution",
        "submodule_zh": "方程的解",
        "tags_en": ["equation", "solution", "example", "linear-equation"],
        "tags_zh": ["方程与不等式", "方程的解", "例题", "一元一次方程"],
        "component_label": "例题讲解",
        "note_zh": "人工审核后替换了原来的概念页。",
    },
    "case_021": {
        "src_run": "rerun_junior_g7_eq_to_equation_v02_20260624",
        "src_name": "tq_006_考点2_方程的解_强化训练_Q变式2-1.png",
        "submodule_en": "equation-solution",
        "submodule_zh": "方程的解",
        "tags_en": ["equation", "solution", "drill", "algebra"],
        "tags_zh": ["方程与不等式", "方程的解", "强化训练", "代数"],
        "component_label": "强化训练",
        "note_zh": "人工审核后替换了原来的概念页。",
    },
    "case_022": {
        "src_run": "rerun_junior_g7_eq_to_equation_v02_20260624",
        "src_name": "tq_011_考点3_一元一次方程_例题讲解_Q例4.png",
        "submodule_en": "linear-equation",
        "submodule_zh": "一元一次方程",
        "tags_en": ["equation", "linear-equation", "example", "solve"],
        "tags_zh": ["方程与不等式", "一元一次方程", "例题", "求解"],
        "component_label": "例题讲解",
        "note_zh": "人工审核后替换了原来的概念页。",
    },
    "case_023": {
        "src_run": "rerun_junior_g7_eq_to_equation_v02_20260624",
        "src_name": "tq_012_考点3_一元一次方程_强化训练_Q变式4-1.png",
        "submodule_en": "linear-equation",
        "submodule_zh": "一元一次方程",
        "tags_en": ["equation", "linear-equation", "drill", "solve"],
        "tags_zh": ["方程与不等式", "一元一次方程", "强化训练", "求解"],
        "component_label": "强化训练",
        "note_zh": "人工审核后替换了原来的概念页。",
    },
    "case_024": {
        "src_run": "rerun_junior_g7_eq_to_equation_v02_20260624",
        "src_name": "tq_020_考点1_等式的性质_例题讲解_Q例7.png",
        "submodule_en": "equality-properties",
        "submodule_zh": "等式的性质",
        "tags_en": ["equation", "equality-properties", "example", "balance"],
        "tags_zh": ["方程与不等式", "等式的性质", "例题", "等量关系"],
        "component_label": "例题讲解",
        "note_zh": "人工审核后替换了原来的思维导图页。",
    },
    "case_025": {
        "src_run": "rerun_junior_quad_eq_ineq_v06_20260624",
        "src_name": "tq_001_考点1_二次函数图象与x_轴的交点_例题讲解_Q例1.png",
        "submodule_en": "quadratic-x-axis-intersection",
        "submodule_zh": "二次函数图象与x轴的交点",
        "tags_en": ["junior-function", "quadratic", "graph", "intersection"],
        "tags_zh": ["初中函数", "二次函数", "图象", "交点"],
        "component_label": "例题讲解",
        "note_zh": "人工审核后替换了原来的知识表。",
    },
    "case_026": {
        "src_run": "rerun_junior_quad_eq_ineq_v06_20260624",
        "src_name": "tq_002_考点1_二次函数图象与x_轴的交点_强化训练_Q变式1-1.png",
        "submodule_en": "quadratic-x-axis-intersection",
        "submodule_zh": "二次函数图象与x轴的交点",
        "tags_en": ["junior-function", "quadratic", "graph", "drill"],
        "tags_zh": ["初中函数", "二次函数", "图象", "强化训练"],
        "component_label": "强化训练",
        "note_zh": "人工审核后替换了原来的知识表。",
    },
    "case_027": {
        "src_run": "rerun_junior_quad_eq_ineq_v06_20260624",
        "src_name": "tq_003_考点1_二次函数图象与x_轴的交点_例题讲解_Q例2.png",
        "submodule_en": "quadratic-x-axis-intersection",
        "submodule_zh": "二次函数图象与x轴的交点",
        "tags_en": ["junior-function", "quadratic", "graph", "example"],
        "tags_zh": ["初中函数", "二次函数", "图象", "例题"],
        "component_label": "例题讲解",
        "note_zh": "人工审核后替换了原来的知识表。",
    },
    "case_028": {
        "src_run": "rerun_junior_quad_eq_ineq_v06_20260624",
        "src_name": "tq_006_考点2_二次函数图象与一次函数图象的交点_例题讲解_Q例3.png",
        "submodule_en": "quadratic-line-intersection",
        "submodule_zh": "二次函数图象与一次函数图象的交点",
        "tags_en": ["junior-function", "quadratic", "linear-function", "intersection"],
        "tags_zh": ["初中函数", "二次函数", "一次函数", "交点"],
        "component_label": "例题讲解",
        "note_zh": "人工审核后替换了原来的单行知识残片。",
    },
    "case_029": {
        "src_run": "rerun_junior_quad_eq_ineq_v06_20260624",
        "src_name": "tq_007_考点2_二次函数图象与一次函数图象的交点_例题讲解_Q例4.png",
        "submodule_en": "quadratic-line-intersection",
        "submodule_zh": "二次函数图象与一次函数图象的交点",
        "tags_en": ["junior-function", "quadratic", "linear-function", "example"],
        "tags_zh": ["初中函数", "二次函数", "一次函数", "例题"],
        "component_label": "例题讲解",
        "note_zh": "人工审核后替换了原来的单行知识残片。",
    },
    "case_030": {
        "src_run": "rerun_junior_quad_eq_ineq_v06_20260624",
        "src_name": "tq_009_考点3_利用函数图象解方程_例题讲解_Q例5.png",
        "submodule_en": "solve-equation-by-graph",
        "submodule_zh": "利用函数图象解方程",
        "tags_en": ["junior-function", "graph", "equation", "solve"],
        "tags_zh": ["初中函数", "函数图象", "方程", "求解"],
        "component_label": "例题讲解",
        "note_zh": "人工审核后替换了原来的知识梳理页。",
    },
    "case_032": {
        "src_run": "rerun_junior_quad_eq_ineq_v06_20260624",
        "src_name": "tq_018_考点4_二次函数与一元二次方程_例题讲解_Q例9.png",
        "submodule_en": "quadratic-and-quadratic-equation",
        "submodule_zh": "二次函数与一元二次方程",
        "tags_en": ["junior-function", "quadratic", "equation", "example"],
        "tags_zh": ["初中函数", "二次函数", "一元二次方程", "例题"],
        "component_label": "例题讲解",
        "note_zh": "人工审核后替换了原来的纯解析续页。",
    },
    "case_037": {
        "src_run": "codex_profile_junior_geometry_transcription_v02_20260624",
        "src_name": "tq_017_考点3_利用平行线+中点构造全等_例题讲解_Q例7.png",
        "submodule_en": "parallel-lines-midpoint-congruence",
        "submodule_zh": "利用平行线加中点构造全等",
        "tags_en": ["plane-geometry", "parallel-line", "midpoint", "congruence"],
        "tags_zh": ["平面几何", "平行线", "中点", "全等"],
        "component_label": "例题讲解",
        "note_zh": "人工审核后替换了原来的做法总结页。",
    },
    "case_098": {
        "src_run": "seed_senior_probability_conditional_v01_20260624",
        "src_name": "tq_028_考点4：全概率公式_例题讲解_Q2.png",
        "submodule_en": "total-probability-formula",
        "submodule_zh": "全概率公式",
        "tags_en": ["probability", "total-probability", "bayes-style", "example"],
        "tags_zh": ["概率统计", "全概率公式", "条件概率", "例题"],
        "component_label": "例题讲解",
        "note_zh": "人工审核后替换了原来的单行残片。",
    },
    "case_099": {
        "src_run": "seed_senior_probability_conditional_v01_20260624",
        "src_name": "tq_041_考点5：事件的独立性_强化训练_Q4.png",
        "submodule_en": "event-independence",
        "submodule_zh": "事件的独立性",
        "tags_en": ["probability", "independence", "counting", "drill"],
        "tags_zh": ["概率统计", "独立性", "计数原理", "强化训练"],
        "component_label": "强化训练",
        "note_zh": "人工审核后替换了原来的题干残片。",
    },
}


def source_image(run_name: str, file_name: str) -> Path:
    return OUTPUTS / "ingress_splitter_v0.1" / run_name / "question_crops" / file_name


def main() -> None:
    if DST_PACK.exists():
        shutil.rmtree(DST_PACK)
    shutil.copytree(SRC_PACK, DST_PACK)

    manifest_path = DST_PACK / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for case in manifest["cases"]:
        case["audit_status"] = "manually_checked_2026_06_24"
        case["needs_human_review"] = False

    for case_id, repl in REPLACEMENTS.items():
        case = next(x for x in manifest["cases"] if x["case_id"] == case_id)
        old_rel = Path(case["packaged_image"])
        old_abs = DST_PACK / old_rel
        if old_abs.exists():
            old_abs.unlink()

        src = source_image(repl["src_run"], repl["src_name"])
        new_name = f"{case_id}__{repl['src_name']}"
        new_rel = old_rel.parent / new_name
        shutil.copy2(src, DST_PACK / new_rel)

        case["submodule_en"] = repl["submodule_en"]
        case["submodule_zh"] = repl["submodule_zh"]
        case["tags_en"] = repl["tags_en"]
        case["tags_zh"] = repl["tags_zh"]
        case["source_type"] = "manual_replacement_after_audit"
        case["source_run"] = repl["src_run"]
        case["source_ref"] = repl["src_name"]
        case["packaged_image"] = new_rel.as_posix()
        case["component_label"] = repl["component_label"]
        case["note_zh"] = repl["note_zh"]

    manifest["package_name"] = DST_PACK.name
    manifest["notes"] = [
        "已完成一次人工逐张审图清洗。",
        "本次移除了非题考点页、知识导图页、纯答案残片、纯解析续页等无效图片。",
        f"共替换 {len(REPLACEMENTS)} 张图片，保留总量 100 题不变。",
    ]
    manifest["replaced_case_ids"] = sorted(REPLACEMENTS.keys())
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = DST_PACK / "manifest.csv"
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
        "needs_human_review",
        "packaged_image",
        "note_zh",
        "audit_status",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in manifest["cases"]:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    readme = [
        "# 数学符号测试图包（人工清洗版）",
        "",
        f"- 包名：`{DST_PACK.name}`",
        "- 总题数：`100`",
        "- 审核方式：按模块总览 + 单张复核，人工移除非题与残片",
        f"- 本次替换：`{len(REPLACEMENTS)}` 张",
        "- 当前状态：这版已经把明显的非题考点页、知识页、思维导图页、纯答案页清掉了",
        "",
        "## 主要文件",
        "",
        "- `manifest.json`：人工清洗后的双语清单",
        "- `manifest.csv`：便于筛选统计",
        "- `images/`：人工清洗后的 100 张题图",
    ]
    (DST_PACK / "README.md").write_text("\n".join(readme), encoding="utf-8")

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
                "replacements": len(REPLACEMENTS),
                "replaced_case_ids": sorted(REPLACEMENTS.keys()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
