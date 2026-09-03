from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "final_chain_samples"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
PACKAGE_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""


def build_docx(path: Path, title: str, body: str) -> None:
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{title}</w:t></w:r></w:p>
    <w:p><w:r><w:t>{body}</w:t></w:r></w:p>
    <w:sectPr/>
  </w:body>
</w:document>
"""
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", PACKAGE_RELS)
        archive.writestr("word/document.xml", document)


def build_pdf(path: Path) -> None:
    document = pymupdf.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "PDF Math Foundation Fixture", fontsize=16)
        page.insert_text((72, 110), "Solve: x + 2 = 5", fontsize=12)
        document.save(path)
    finally:
        document.close()


def main() -> int:
    # 这些文件只证明适配器能读取真实容器格式，不代表生产内容质量验收。
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    build_docx(FIXTURE_ROOT / "doc_math_sample.docx", "DOC Math Foundation Fixture", "Solve: x + 2 = 5")
    build_docx(
        FIXTURE_ROOT / "doc_english_sample.docx",
        "DOC English Foundation Fixture",
        "Read the sentence and choose the correct answer.",
    )
    build_pdf(FIXTURE_ROOT / "pdf_math_sample.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
