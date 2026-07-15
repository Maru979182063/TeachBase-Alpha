from pathlib import Path
from xml.etree import ElementTree as ET

import json
import sys


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import docx_native_formula_token_stream_v01 as stream
from docx_native_formula_providers import LegacyMtefManifestProvider, OmmlLatexProvider


W = stream.NS["w"]
M = stream.NS["m"]
R = stream.NS["r"]
A = stream.NS["a"]
WP = stream.NS["wp"]


def paragraph(fragment: str) -> ET.Element:
    return ET.fromstring(
        f'<w:p xmlns:w="{W}" xmlns:m="{M}" xmlns:r="{R}" xmlns:a="{A}" xmlns:wp="{WP}">{fragment}</w:p>'
    )


def test_serialize_paragraph_keeps_formula_tokens_and_run_scripts() -> None:
    p = paragraph(
        """
        <w:r><w:t>AB</w:t></w:r>
        <w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:t>2</w:t></w:r>
        <m:oMath><m:f><m:num><m:r><m:t>1</m:t></m:r></m:num><m:den><m:r><m:t>x</m:t></m:r></m:den></m:f></m:oMath>
        <m:oMath><m:rad><m:deg/><m:e><m:r><m:t>y</m:t></m:r></m:e></m:rad></m:oMath>
        """
    )

    block = stream.serialize_paragraph(
        p,
        rels={},
        media={},
        image_counter=[0],
        omml_provider=OmmlLatexProvider(),
        mtef_provider=LegacyMtefManifestProvider(),
    )

    assert "AB$^{2}" in block["markdown"]
    assert r"\frac{1}{x}" in block["markdown"]
    assert r"\sqrt{y}" in block["markdown"]
    assert block["formula_count"] == 2
    assert any(item["type"] == "run_superscript" for item in block["formula_findings"])


def test_image_asset_placeholder_is_preserved() -> None:
    p = paragraph(
        """
        <w:r>
          <w:drawing><wp:inline><a:blip r:embed="rIdImage1"/></wp:inline></w:drawing>
        </w:r>
        """
    )
    media = {
        "word/media/image1.png": {
            "asset_id": "docx_media_0001",
            "storage_key": "tests/fixtures/docx_native_repair_v01/image1.png",
        }
    }
    block = stream.serialize_paragraph(
        p,
        rels={"rIdImage1": "word/media/image1.png"},
        media=media,
        image_counter=[0],
        omml_provider=OmmlLatexProvider(),
        mtef_provider=LegacyMtefManifestProvider(),
    )

    assert "![docx_media_0001](asset://docx_media_0001)" in block["markdown"]
    assert block["image_refs"][0]["asset_id"] == "docx_media_0001"


def test_build_packets_from_boundaries_marks_no_runtime_or_db(tmp_path) -> None:
    paragraphs = [
        {"markdown": "Question $x^{2}$", "image_refs": [], "paragraph_index": 0},
        {
            "markdown": "![docx_media_0001](asset://docx_media_0001)",
            "image_refs": [{"asset_id": "docx_media_0001"}],
            "paragraph_index": 1,
        },
    ]
    boundaries = tmp_path / "boundaries.json"
    boundaries.write_text(
        json.dumps({"questions": [{"question_id": "q1", "order_index": 1, "start_paragraph_index": 0, "end_paragraph_index": 1}]}),
        encoding="utf-8",
    )

    manifest = stream.build_packets_from_boundaries(paragraphs, [], boundaries, tmp_path)

    assert manifest["no_runtime_import"] is True
    assert manifest["no_database_write"] is True
    assert manifest["questions"][0]["asset_ids"] == ["docx_media_0001"]
    assert "asset://docx_media_0001" in manifest["questions"][0]["display_markdown"]
