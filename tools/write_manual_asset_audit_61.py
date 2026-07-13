import csv
import json
from pathlib import Path


ROOT = Path("outputs/external_instance_packs/math_208_transcription_plus_assets_latest_20260702")


AUDIT_ROWS = [
    ("case_004", "pass", "clean", "数轴/坐标类主体图完整，边界可接受。"),
    ("case_005", "pass", "clean", "数轴图完整，插入可用。"),
    ("case_007", "pass", "clean", "线段图完整，留白略多但不影响入库展示。"),
    ("case_028", "pass", "clean", "函数图完整。"),
    ("case_032", "pass_with_note", "redundant_assets", "主体函数图完整，但存在重复/多版本图。"),
    ("case_033", "pass", "clean", "几何图完整。"),
    ("case_034", "pass", "clean", "两张解析图完整，前序作用域问题本轮已改善。"),
    ("case_035", "pass", "clean", "题干/解析图完整。"),
    ("case_036", "pass", "clean", "多张几何图完整。"),
    ("case_037", "pass", "clean", "题干/解析图完整。"),
    ("case_038", "pass", "clean", "多图完整。"),
    ("case_039", "pass", "clean", "题干/解析图完整。"),
    ("case_040", "pass", "clean", "图形完整。"),
    ("case_041", "pass", "clean", "图形完整。"),
    ("case_054", "fail", "fragmented_option_region", "函数对应关系多小图被切成 10 个碎片，含半图、重复图、残图；作为题内插图不可用。"),
    ("case_055", "pass", "clean", "A/B/C/D 四个选项图完整。"),
    ("case_078", "pass", "clean", "解析图完整。"),
    ("case_079", "pass", "clean", "题干图完整。"),
    ("case_086", "pass_with_note", "redundant_assets", "主体图完整，但有重复/多版本资产。"),
    ("case_107", "fail", "missing_clean_analysis_figure", "题干图完整，但解析图切成残片，原题后续完整图未干净挂出。"),
    ("case_108", "pass_with_note", "redundant_assets", "主体图均可见，但资产过多，有重复/过切。"),
    ("case_109", "pass", "clean", "多图完整。"),
    ("case_110", "pass", "clean", "题干图完整。"),
    ("case_111", "pass_with_note", "redundant_assets", "主体图可见，但重复/过切明显。"),
    ("case_112", "pass_with_note", "duplicate_assets", "解析图可见，但存在重复图。"),
    ("case_113", "pass", "clean", "图1/图2/图3等主体图完整，去重后可用。"),
    ("case_114", "pass", "clean", "题干图完整。"),
    ("case_115", "pass", "clean", "题干/解析图完整。"),
    ("case_116", "pass", "clean", "题干/解析图完整。"),
    ("case_117", "pass_with_note", "redundant_assets", "主体图完整，但存在重复/多切。"),
    ("case_118", "pass_with_note", "redundant_assets", "主体图完整，但存在重复/多切。"),
    ("case_119", "pass_with_note", "redundant_assets", "主体图完整，但资产偏多。"),
    ("case_120", "fail", "mixed_text_and_duplicate_assets", "图都能找到，但误切出文字+半张图资产，且重复图较多；直接插入会污染页面。"),
    ("case_121", "pass", "clean", "主体图完整。"),
    ("case_122", "pass", "clean", "题干/解析图完整。"),
    ("case_123", "pass_with_note", "minor_text_margin", "主体图完整，个别资产带少量文字边缘。"),
    ("case_124", "pass", "clean", "主体图完整。"),
    ("case_125", "pass", "clean", "题干图完整。"),
    ("case_126", "pass", "clean", "题干图完整。"),
    ("case_127", "pass", "clean", "两张三角形图完整，前序上下截断问题本轮未复现。"),
    ("case_128", "pass_with_note", "redundant_assets", "主体图完整，但存在重复/多切。"),
    ("case_129", "pass", "clean", "四张几何图完整。"),
    ("case_130", "pass_with_note", "redundant_assets", "主体图完整，但存在重复/多切。"),
    ("case_131", "pass", "clean", "题干图完整。"),
    ("case_132", "pass", "clean", "题干图完整。"),
    ("case_133", "pass", "clean", "题干/解析图完整。"),
    ("case_134", "pass", "clean", "主体图完整。"),
    ("case_135", "fail", "dirty_analysis_crop", "多张图被切成图+大量解析文字/页眉，资产边界错误；不适合入库插图。"),
    ("case_136", "pass", "clean", "题干图完整。"),
    ("case_140", "pass", "clean", "A/B/C/D 四个选项图完整。"),
    ("case_141", "pass_with_note", "duplicate_assets", "主体图完整，但有重复。"),
    ("case_143", "pass", "clean", "解析图完整。"),
    ("case_148", "pass", "clean", "A/B/C/D 四个选项图完整。"),
    ("case_173", "pass", "clean", "解析图完整。"),
    ("case_177", "pass", "clean", "解析图完整。"),
    ("case_178", "pass", "clean", "题干图完整。"),
    ("case_180", "pass", "clean", "空间向量图完整，存在轻微重复但不影响主体图。"),
    ("case_186", "pass", "clean", "题干图完整。"),
    ("case_194", "pass", "clean", "解析图完整。"),
    ("case_196", "pass", "clean", "题干图完整。"),
    ("case_203", "pass_with_note", "redundant_assets", "圆综合图完整，但有重复和少量文字边缘。"),
]


def main() -> None:
    out_dir = ROOT / "tables"
    json_dir = ROOT / "json"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_dir.mkdir(parents=True, exist_ok=True)

    rows = [
        {
            "case_id": case_id,
            "manual_asset_status": status,
            "issue_type": issue_type,
            "manual_asset_note": note,
        }
        for case_id, status, issue_type, note in AUDIT_ROWS
    ]

    summary = {}
    for row in rows:
        summary[row["manual_asset_status"]] = summary.get(row["manual_asset_status"], 0) + 1
    issue_summary = {}
    for row in rows:
        issue_summary[row["issue_type"]] = issue_summary.get(row["issue_type"], 0) + 1

    csv_path = out_dir / "manual_image_asset_audit_61.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["case_id", "manual_asset_status", "issue_type", "manual_asset_note"],
        )
        writer.writeheader()
        writer.writerows(rows)

    json_path = json_dir / "manual_image_asset_audit_61.json"
    json_path.write_text(
        json.dumps(
            {
                "schema_version": "manual_image_asset_audit.v1",
                "audit_scope": "61 cases with inserted content assets in latest 208 instance pack",
                "status_definition": {
                    "pass": "人工对照原图后，主体题内图完整且可直接用于入库展示。",
                    "pass_with_note": "主体题内图完整可用，但存在重复、轻微文字边缘或资产偏多，后续可优化。",
                    "fail": "人工对照原图后，存在少图、残图、误切文本块或插入会污染页面的问题。",
                },
                "summary": summary,
                "issue_summary": issue_summary,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(json.dumps({"csv": str(csv_path), "json": str(json_path), "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
