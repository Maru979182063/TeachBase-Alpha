from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
OLD_PACK = OUTPUTS / "math_symbol_image_pack_100q_20260624"
NEW_PACK = OUTPUTS / "math_symbol_image_pack_100q_20260624_bilingual"


MODULE_SPECS = [
    {
        "key": "01_basic_numbers",
        "folder_en": "01_basic_numbers",
        "folder_zh": "基础数与式",
        "keep": 16,
        "submodule_en": "legacy_curated",
        "submodule_zh": "既有精选样本",
        "tags_en": ["number", "expression", "fraction", "scientific-notation"],
        "tags_zh": ["数与式", "分数", "幂与指数", "科学记数法"],
    },
    {
        "key": "02_equation_inequality",
        "folder_en": "02_equation_inequality",
        "folder_zh": "方程与不等式",
        "keep": 8,
        "submodule_en": "legacy_curated",
        "submodule_zh": "既有精选样本",
        "tags_en": ["equation", "inequality", "root", "parameter"],
        "tags_zh": ["方程", "不等式", "根式", "参数"],
    },
    {
        "key": "03_junior_functions",
        "folder_en": "03_junior_functions",
        "folder_zh": "初中函数",
        "keep": 8,
        "submodule_en": "legacy_curated",
        "submodule_zh": "既有精选样本",
        "tags_en": ["function", "graph", "coordinate", "change-rate"],
        "tags_zh": ["函数", "图像", "坐标系", "变化率"],
    },
    {
        "key": "04_plane_geometry",
        "folder_en": "04_plane_geometry",
        "folder_zh": "平面几何",
        "keep": 9,
        "submodule_en": "legacy_curated",
        "submodule_zh": "既有精选样本",
        "tags_en": ["plane-geometry", "triangle", "circle", "proof"],
        "tags_zh": ["平面几何", "三角形", "圆", "证明"],
    },
    {
        "key": "05_sets_logic",
        "folder_en": "05_sets_logic",
        "folder_zh": "集合与逻辑",
        "keep": 12,
        "submodule_en": "legacy_curated",
        "submodule_zh": "既有精选样本",
        "tags_en": ["set", "logic", "interval", "quantifier"],
        "tags_zh": ["集合", "逻辑", "区间", "量词"],
    },
    {
        "key": "06_senior_functions",
        "folder_en": "06_senior_functions",
        "folder_zh": "高中函数",
        "keep": 8,
        "submodule_en": "legacy_curated",
        "submodule_zh": "既有精选样本",
        "tags_en": ["function", "domain", "range", "monotonicity"],
        "tags_zh": ["函数", "定义域", "值域", "单调性"],
    },
    {
        "key": "07_trigonometry",
        "folder_en": "07_trigonometry",
        "folder_zh": "三角函数",
        "keep": 8,
        "submodule_en": "legacy_curated",
        "submodule_zh": "既有精选样本",
        "tags_en": ["trigonometry", "sin-cos-tan", "identity", "triangle"],
        "tags_zh": ["三角函数", "正弦余弦正切", "恒等变换", "解三角形"],
    },
    {
        "key": "08_analytic_geometry",
        "folder_en": "08_analytic_geometry",
        "folder_zh": "解析几何",
        "keep": 8,
        "submodule_en": "legacy_curated",
        "submodule_zh": "既有精选样本",
        "tags_en": ["analytic-geometry", "line", "circle", "conic"],
        "tags_zh": ["解析几何", "直线", "圆", "圆锥曲线"],
    },
    {
        "key": "09_solid_geometry_vectors",
        "folder_en": "09_solid_geometry_vectors",
        "folder_zh": "立体几何与向量",
        "keep": 5,
        "submodule_en": "legacy_curated",
        "submodule_zh": "既有精选样本",
        "tags_en": ["solid-geometry", "vector", "space-angle", "distance"],
        "tags_zh": ["立体几何", "向量", "空间角", "距离"],
    },
    {
        "key": "10_derivative_complex",
        "folder_en": "10_derivative_complex",
        "folder_zh": "导数与复数",
        "keep": 6,
        "submodule_en": "legacy_curated",
        "submodule_zh": "既有精选样本",
        "tags_en": ["derivative", "complex", "tangent", "extremum"],
        "tags_zh": ["导数", "复数", "切线", "最值"],
    },
    {
        "key": "11_sequences",
        "folder_en": "11_sequences",
        "folder_zh": "数列",
        "keep": 0,
        "submodule_en": "sequence_curated",
        "submodule_zh": "新增数列样本",
        "tags_en": ["sequence", "arithmetic", "recurrence", "sum"],
        "tags_zh": ["数列", "等差数列", "递推", "求和"],
    },
    {
        "key": "12_probability_statistics",
        "folder_en": "12_probability_statistics",
        "folder_zh": "概率统计",
        "keep": 0,
        "submodule_en": "probability_curated",
        "submodule_zh": "新增概率统计样本",
        "tags_en": ["probability", "conditional-probability", "independence", "counting"],
        "tags_zh": ["概率统计", "条件概率", "独立性", "计数原理"],
    },
]


NEW_CASES = [
    {
        "module_key": "11_sequences",
        "source_run": "seed_senior_sequence_arith_v02_20260624",
        "prefix": "tq_001_",
        "submodule_en": "arithmetic-sequence-basics",
        "submodule_zh": "等差数列基础公式与性质",
        "tags_en": ["sequence", "arithmetic", "general-term", "formula"],
        "tags_zh": ["数列", "等差数列", "通项公式", "基础公式"],
        "component_label": "题目区回退",
        "note_zh": "该讲义的组件标题文本层缺失，已用题号回退规则切出。",
    },
    {
        "module_key": "11_sequences",
        "source_run": "seed_senior_sequence_arith_v02_20260624",
        "prefix": "tq_002_",
        "submodule_en": "arithmetic-sequence-basics",
        "submodule_zh": "等差数列基础公式与性质",
        "tags_en": ["sequence", "arithmetic", "sum", "parameter"],
        "tags_zh": ["数列", "等差数列", "前n项和", "参数"],
        "component_label": "题目区回退",
        "note_zh": "该讲义的组件标题文本层缺失，已用题号回退规则切出。",
    },
    {
        "module_key": "11_sequences",
        "source_run": "seed_senior_sequence_arith_v02_20260624",
        "prefix": "tq_004_",
        "submodule_en": "arithmetic-sequence-basics",
        "submodule_zh": "等差数列基础公式与性质",
        "tags_en": ["sequence", "arithmetic", "fill-blank", "solve-for-n"],
        "tags_zh": ["数列", "等差数列", "填空题", "求n"],
        "component_label": "题目区回退",
        "note_zh": "该讲义的组件标题文本层缺失，已用题号回退规则切出。",
    },
    {
        "module_key": "11_sequences",
        "source_run": "seed_senior_sequence_sumrec_v02_20260624",
        "prefix": "tq_001_",
        "submodule_en": "sum-to-term-recurrence",
        "submodule_zh": "和与和递推求通项",
        "tags_en": ["sequence", "recurrence", "piecewise", "sum-to-term"],
        "tags_zh": ["数列", "递推", "分段通项", "和与和递推"],
        "component_label": "题目区回退",
        "note_zh": "该讲义的组件标题文本层缺失，已用题号回退规则切出。",
    },
    {
        "module_key": "11_sequences",
        "source_run": "seed_senior_sequence_sumrec_v02_20260624",
        "prefix": "tq_007_",
        "submodule_en": "term-and-sum-recurrence",
        "submodule_zh": "项与和递推求通项",
        "tags_en": ["sequence", "recurrence", "Sn", "an"],
        "tags_zh": ["数列", "递推", "S_n", "a_n"],
        "component_label": "题目区回退",
        "note_zh": "该讲义的组件标题文本层缺失，已用题号回退规则切出。",
    },
    {
        "module_key": "11_sequences",
        "source_run": "seed_senior_sequence_sumrec_v02_20260624",
        "prefix": "tq_012_",
        "submodule_en": "special-sum-to-term",
        "submodule_zh": "特殊和求通项",
        "tags_en": ["sequence", "special-sum", "transform", "general-term"],
        "tags_zh": ["数列", "特殊和", "变形", "通项"],
        "component_label": "题目区回退",
        "note_zh": "该讲义的组件标题文本层缺失，已用题号回退规则切出。",
    },
    {
        "module_key": "12_probability_statistics",
        "source_run": "seed_senior_probability_conditional_v01_20260624",
        "prefix": "tq_001_",
        "submodule_en": "classical-probability-via-counting",
        "submodule_zh": "利用排列组合计算古典概型",
        "tags_en": ["probability", "classical", "counting", "combination"],
        "tags_zh": ["概率统计", "古典概型", "排列组合", "组合计数"],
        "component_label": "例题讲解",
        "note_zh": "来自新增概率统计教师版讲义。",
    },
    {
        "module_key": "12_probability_statistics",
        "source_run": "seed_senior_probability_conditional_v01_20260624",
        "prefix": "tq_011_",
        "submodule_en": "probability-multiplication-rule",
        "submodule_zh": "概率乘法公式",
        "tags_en": ["probability", "multiplication-rule", "event", "tree"],
        "tags_zh": ["概率统计", "乘法公式", "事件", "分步概率"],
        "component_label": "例题讲解",
        "note_zh": "来自新增概率统计教师版讲义。",
    },
    {
        "module_key": "12_probability_statistics",
        "source_run": "seed_senior_probability_conditional_v01_20260624",
        "prefix": "tq_017_",
        "submodule_en": "conditional-probability",
        "submodule_zh": "条件概率公式的概念与应用",
        "tags_en": ["probability", "conditional-probability", "event", "fraction"],
        "tags_zh": ["概率统计", "条件概率", "事件", "分式概率"],
        "component_label": "例题讲解",
        "note_zh": "来自新增概率统计教师版讲义。",
    },
    {
        "module_key": "12_probability_statistics",
        "source_run": "seed_senior_probability_conditional_v01_20260624",
        "prefix": "tq_027_",
        "submodule_en": "total-probability-formula",
        "submodule_zh": "全概率公式",
        "tags_en": ["probability", "total-probability", "partition", "formula"],
        "tags_zh": ["概率统计", "全概率公式", "划分事件", "公式推导"],
        "component_label": "例题讲解",
        "note_zh": "来自新增概率统计教师版讲义。",
    },
    {
        "module_key": "12_probability_statistics",
        "source_run": "seed_senior_probability_conditional_v01_20260624",
        "prefix": "tq_037_",
        "submodule_en": "event-independence",
        "submodule_zh": "事件的独立性",
        "tags_en": ["probability", "independence", "event", "multiplication"],
        "tags_zh": ["概率统计", "独立性", "事件", "乘法公式"],
        "component_label": "例题讲解",
        "note_zh": "来自新增概率统计教师版讲义。",
    },
    {
        "module_key": "12_probability_statistics",
        "source_run": "seed_senior_probability_conditional_v01_20260624",
        "prefix": "tq_046_",
        "submodule_en": "event-independence-after-class",
        "submodule_zh": "事件的独立性课后落实",
        "tags_en": ["probability", "independence", "after-class", "application"],
        "tags_zh": ["概率统计", "独立性", "课后落实", "应用题"],
        "component_label": "课后落实",
        "note_zh": "来自新增概率统计教师版讲义。",
    },
]


def pick_file(run_name: str, prefix: str) -> Path:
    run_dir = OUTPUTS / "ingress_splitter_v0.1" / run_name / "question_crops"
    matches = sorted(p for p in run_dir.iterdir() if p.is_file() and p.name.startswith(prefix))
    if not matches:
        raise FileNotFoundError(f"{run_name} :: {prefix}")
    return matches[0]


def build_readme(module_counts_en: dict[str, int]) -> str:
    module_lines = [
        ("01_basic_numbers", "基础数与式"),
        ("02_equation_inequality", "方程与不等式"),
        ("03_junior_functions", "初中函数"),
        ("04_plane_geometry", "平面几何"),
        ("05_sets_logic", "集合与逻辑"),
        ("06_senior_functions", "高中函数"),
        ("07_trigonometry", "三角函数"),
        ("08_analytic_geometry", "解析几何"),
        ("09_solid_geometry_vectors", "立体几何与向量"),
        ("10_derivative_complex", "导数与复数"),
        ("11_sequences", "数列"),
        ("12_probability_statistics", "概率统计"),
    ]
    lines = [
        "# 数学符号测试图包（双语版）",
        "",
        f"- 包名：`{NEW_PACK.name}`",
        "- 总题数：`100`",
        "- 本次新增：`数列`、`概率统计`",
        "- 本次补充：目录名、模块标签、子模块标签、标签字段均提供中英双语",
        "- 特别说明：`数列`样本使用了“题目区回退”规则，建议后续验收时重点看这 6 题",
        "",
        "## 模块对照",
        "",
        "| English | 中文 | 数量 |",
        "|---|---|---:|",
    ]
    for en, zh in module_lines:
        lines.append(f"| `{en}` | {zh} | {module_counts_en.get(en, 0)} |")
    lines.extend(
        [
            "",
            "## 主要文件",
            "",
            "- `manifest.json`：完整双语清单",
            "- `manifest.csv`：便于筛选统计",
            "- `images/`：按中英双语目录分模块存放的题图",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    if NEW_PACK.exists():
        shutil.rmtree(NEW_PACK)
    (NEW_PACK / "images").mkdir(parents=True, exist_ok=True)

    spec_by_key = {spec["key"]: spec for spec in MODULE_SPECS}
    cases: list[dict] = []
    case_no = 1

    for spec in MODULE_SPECS[:10]:
        src_dir = OLD_PACK / "images" / spec["key"]
        files = sorted(p for p in src_dir.iterdir() if p.is_file())[: spec["keep"]]
        target_dir = NEW_PACK / "images" / f"{spec['folder_en']}__{spec['folder_zh']}"
        target_dir.mkdir(parents=True, exist_ok=True)
        for src in files:
            case_id = f"case_{case_no:03d}"
            dst_name = f"{case_id}__{src.name}"
            dst_rel = Path("images") / target_dir.name / dst_name
            shutil.copy2(src, NEW_PACK / dst_rel)
            cases.append(
                {
                    "case_id": case_id,
                    "module_en": spec["folder_en"],
                    "module_zh": spec["folder_zh"],
                    "submodule_en": spec["submodule_en"],
                    "submodule_zh": spec["submodule_zh"],
                    "tags_en": spec["tags_en"],
                    "tags_zh": spec["tags_zh"],
                    "source_type": "reused_from_v1_pack",
                    "source_run": OLD_PACK.name,
                    "source_ref": src.name,
                    "packaged_image": dst_rel.as_posix(),
                    "component_label": "",
                    "note_zh": "沿用旧包样本，保留原图作为符号测试图。",
                    "needs_human_review": False,
                }
            )
            case_no += 1

    for item in NEW_CASES:
        spec = spec_by_key[item["module_key"]]
        src = pick_file(item["source_run"], item["prefix"])
        target_dir = NEW_PACK / "images" / f"{spec['folder_en']}__{spec['folder_zh']}"
        target_dir.mkdir(parents=True, exist_ok=True)
        case_id = f"case_{case_no:03d}"
        dst_name = f"{case_id}__{src.name}"
        dst_rel = Path("images") / target_dir.name / dst_name
        shutil.copy2(src, NEW_PACK / dst_rel)
        cases.append(
            {
                "case_id": case_id,
                "module_en": spec["folder_en"],
                "module_zh": spec["folder_zh"],
                "submodule_en": item["submodule_en"],
                "submodule_zh": item["submodule_zh"],
                "tags_en": item["tags_en"],
                "tags_zh": item["tags_zh"],
                "source_type": "new_split_case",
                "source_run": item["source_run"],
                "source_ref": src.name,
                "packaged_image": dst_rel.as_posix(),
                "component_label": item["component_label"],
                "note_zh": item["note_zh"],
                "needs_human_review": item["component_label"] == "题目区回退",
            }
        )
        case_no += 1

    if len(cases) != 100:
        raise RuntimeError(f"Expected 100 cases, got {len(cases)}")

    module_counts_en = dict(Counter(case["module_en"] for case in cases))
    module_counts_zh = dict(Counter(case["module_zh"] for case in cases))
    manifest = {
        "package_name": NEW_PACK.name,
        "case_count": len(cases),
        "module_counts_en": module_counts_en,
        "module_counts_zh": module_counts_zh,
        "notes": [
            "本版补入此前缺失的数列与概率统计样本。",
            "目录、模块标签、子模块标签、标签字段均提供中英双语。",
            "数列样本使用了组件标题缺失时的题号回退切分规则，因此标记为 needs_human_review=true，方便后续重点验收。",
        ],
        "cases": cases,
    }

    with (NEW_PACK / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

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
    ]
    with (NEW_PACK / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in cases:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    (NEW_PACK / "README.md").write_text(build_readme(module_counts_en), encoding="utf-8")

    zip_path = OUTPUTS / f"{NEW_PACK.name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zf:
        for path in sorted(NEW_PACK.rglob("*")):
            zf.write(path, path.relative_to(NEW_PACK.parent))

    print(
        json.dumps(
            {
                "out_dir": str(NEW_PACK),
                "zip": str(zip_path),
                "case_count": len(cases),
                "module_counts_en": module_counts_en,
                "module_counts_zh": module_counts_zh,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
