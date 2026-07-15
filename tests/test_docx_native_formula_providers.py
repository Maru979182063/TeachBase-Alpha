from pathlib import Path
from xml.etree import ElementTree as ET

import sys


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from docx_native_formula_providers import LegacyMtefManifestProvider, OmmlLatexProvider, normalize_latex_notation


M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
O = "urn:schemas-microsoft-com:office:office"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def omml(fragment: str) -> ET.Element:
    return ET.fromstring(
        f'<m:oMath xmlns:m="{M}" xmlns:o="{O}" xmlns:r="{R}">{fragment}</m:oMath>'
    )


def run(text: str) -> str:
    return f"<m:r><m:t>{text}</m:t></m:r>"


def test_omml_provider_serializes_common_formula_shapes() -> None:
    provider = OmmlLatexProvider()

    frac = omml(f"<m:f><m:num>{run('1')}</m:num><m:den>{run('x')}</m:den></m:f>")
    sup = omml(f"<m:sSup><m:e>{run('x')}</m:e><m:sup>{run('2')}</m:sup></m:sSup>")
    sub = omml(f"<m:sSub><m:e>{run('a')}</m:e><m:sub>{run('1')}</m:sub></m:sSub>")
    root = omml(f"<m:rad><m:deg/><m:e>{run('x+1')}</m:e></m:rad>")
    system = omml(f"<m:eqArr><m:e>{run('x=1')}</m:e><m:e>{run('y=2')}</m:e></m:eqArr>")
    overbrace = omml(f"<m:groupChr><m:e>{run('AB')}</m:e></m:groupChr>")

    assert provider.serialize(frac) == r"\frac{1}{x}"
    assert provider.serialize(sup) == "x^{2}"
    assert provider.serialize(sub) == "a_{1}"
    assert provider.serialize(root) == r"\sqrt{x+1}"
    assert provider.serialize(system) == r"x=1 \\ y=2"
    assert provider.serialize(overbrace) == r"\overbrace{AB}"


def test_geometry_arc_notation_is_normalized() -> None:
    assert normalize_latex_notation(r"BD\frown") == r"\overset{\frown}{BD}"


def test_legacy_mtef_manifest_provider_returns_converted_and_missing_tokens(tmp_path) -> None:
    manifest = tmp_path / "mtef_manifest.json"
    manifest.write_text(
        '{"formulas":[{"source":"legacy_equation_mtef","ole_rid":"rId7","latex":"x+y","formula_id":"f7","status":"converted"}]}',
        encoding="utf-8",
    )
    provider = LegacyMtefManifestProvider(manifest)
    converted_run = ET.fromstring(f'<w:r xmlns:w="w" xmlns:o="{O}" xmlns:r="{R}"><o:OLEObject r:id="rId7"/></w:r>')
    missing_run = ET.fromstring(f'<w:r xmlns:w="w" xmlns:o="{O}" xmlns:r="{R}"><o:OLEObject r:id="rId8"/></w:r>')

    converted = provider.token_for_run(converted_run)
    missing = provider.token_for_run(missing_run)

    assert converted is not None
    assert converted.markdown == "$x+y$"
    assert converted.formula_id == "f7"
    assert provider.converted_count == 1
    assert missing is not None
    assert missing.status == "mtef_missing_manifest"
