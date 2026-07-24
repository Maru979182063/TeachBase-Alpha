from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
SRC_PACK = OUTPUTS / "math_symbol_image_pack_200q_20260624_production_curated"
GOLD_PACK = OUTPUTS / "math_symbol_image_pack_168q_20260624_strict_gold"
EDGE_PACK = OUTPUTS / "math_symbol_image_pack_032q_20260624_edge_stress"


EDGE_SOURCE_RUNS = {
    "seed_senior_trig_identity_letters_20260624",
    "seed_senior_sequence_arith_v02_20260624",
    "seed_senior_sequence_sumrec_v02_20260624",
    "seed_senior_ellipse_20260624",
    "seed_senior_hyperbola_20260624",
}


def write_pack(dst_pack: Path, cases: list[dict], notes: list[str]) -> None:
    if dst_pack.exists():
        shutil.rmtree(dst_pack)
    (dst_pack / "images").mkdir(parents=True, exist_ok=True)

    for case in cases:
        rel = Path(case["packaged_image"])
        src = SRC_PACK / rel
        dst = dst_pack / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    manifest = {
        "package_name": dst_pack.name,
        "case_count": len(cases),
        "module_counts_en": dict(Counter(c["module_en"] for c in cases)),
        "module_counts_zh": dict(Counter(c["module_zh"] for c in cases)),
        "notes": notes,
        "cases": cases,
    }
    (dst_pack / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

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
    with (dst_pack / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in cases:
            out = dict(row)
            out["tags_en"] = ";".join(out.get("tags_en", []))
            out["tags_zh"] = ";".join(out.get("tags_zh", []))
            writer.writerow({k: out.get(k, "") for k in fieldnames})

    readme = [
        f"# {dst_pack.name}",
        "",
        f"- 总题量：`{len(cases)}`",
        "- 说明：见 `manifest.json` 的 `notes` 字段。",
    ]
    (dst_pack / "README.md").write_text("\n".join(readme), encoding="utf-8")

    zip_path = OUTPUTS / f"{dst_pack.name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zf:
        for path in sorted(dst_pack.rglob("*")):
            zf.write(path, path.relative_to(dst_pack.parent))


def main() -> None:
    src_manifest = json.loads((SRC_PACK / "manifest.json").read_text(encoding="utf-8"))
    gold_cases: list[dict] = []
    edge_cases: list[dict] = []

    for case in src_manifest["cases"]:
        cloned = dict(case)
        if cloned["source_run"] in EDGE_SOURCE_RUNS:
            edge_cases.append(cloned)
        else:
            gold_cases.append(cloned)

    if len(gold_cases) != 168 or len(edge_cases) != 32:
        raise RuntimeError(f"Unexpected split sizes: gold={len(gold_cases)} edge={len(edge_cases)}")

    write_pack(
        GOLD_PACK,
        gold_cases,
        notes=[
            "从 200 题生产压测包中剔除了 32 张边界压力样本。",
            "本包保留更适合作为题级主金标的 168 张样本。",
            "剔除项主要包括：页级课后题切片、题目区回退样本、以及更偏压力回归用途的样本。",
        ],
    )
    write_pack(
        EDGE_PACK,
        edge_cases,
        notes=[
            "本包为从 200 题生产压测包中拆出的 32 张边界压力样本。",
            "这些样本仍有价值，但更适合做压力回归，不建议直接混入题级主金标。",
            "典型问题包括：页级课后题切片、多题同图、回退切图产生的跨题边界。",
        ],
    )

    print(
        json.dumps(
            {
                "gold_out_dir": str(GOLD_PACK),
                "gold_count": len(gold_cases),
                "edge_out_dir": str(EDGE_PACK),
                "edge_count": len(edge_cases),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
