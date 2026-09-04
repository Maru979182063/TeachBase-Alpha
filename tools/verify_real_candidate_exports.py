"""核对真实题包导出文件里的图片、原生公式和圈号，不以 HTTP completed 代替内容验收。"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from pypdf import PdfReader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    root = parser.parse_args().run_dir
    exports = json.loads((root / "exports.json").read_text(encoding="utf-8"))
    results = []
    for export in exports:
        audience, format_ = export["audience"], export["format"]
        snapshot = json.loads((root / f"{audience}-snapshot.json").read_text(encoding="utf-8"))
        nodes = snapshot["frozenContent"]["projectedDoc"]["content"]
        markdown = "\n\n".join(n.get("attrs", {}).get(audience + "Markdown", "") for n in nodes)
        image_ids = {p.split(")", 1)[0] for p in markdown.split("(tbasset:")[1:]}
        file = next((root / "storage" / "exports").rglob(export["export_request_id"] + "." + format_))
        result = {"audience": audience, "format": format_, "file": str(file),
                  "sha256": hashlib.sha256(file.read_bytes()).hexdigest(), "expectedImages": len(image_ids)}
        if format_ == "docx":
            with zipfile.ZipFile(file) as z:
                text = z.read("word/document.xml").decode("utf-8")
                result["images"] = sum(n.startswith("word/media/") for n in z.namelist())
                result["nativeMath"] = text.count("<m:oMath>")
                assert result["nativeMath"] > 0, "native_word_math_missing"
        else:
            pdf = PdfReader(file)
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            result["pages"] = len(pdf.pages)
            result["images"] = len({hashlib.sha256(i.data).hexdigest() for page in pdf.pages for i in page.images})
            assert "集合" in text, "pdf_chinese_text_missing"
        assert result["images"] == len(image_ids), f"image_count_mismatch:{audience}:{format_}"
        assert "docx_media_" not in text, "technical_asset_caption_leaked"
        assert "textcircled" not in text, "unrendered_circled_command"
        for n in range(1, 21):
            assert text.count(chr(0x2460 + n - 1)) >= markdown.count("\\textcircled{" + str(n) + "}"), "circled_number_missing"
        result["passed"] = True
        results.append(result)
    assert len(results) == 4, "expected_four_audience_format_exports"
    (root / "artifact-qa.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "passed", "files": len(results), "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
