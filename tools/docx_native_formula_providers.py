from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


NS = {
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "o": "urn:schemas-microsoft-com:office:office",
}


def qn(prefix: str, name: str) -> str:
    return f"{{{NS[prefix]}}}{name}"


def lname(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def omml_text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(node.text or "" for node in el.iter() if lname(node) == "t")


def child(parent: ET.Element, name: str) -> ET.Element | None:
    return parent.find(f"m:{name}", NS)


def attr_val(el: ET.Element | None, default: str = "") -> str:
    if el is None:
        return default
    return el.attrib.get(qn("m", "val"), default)


def _take_arc_operand(prefix: str) -> tuple[str, str]:
    """Take a trailing Latin point sequence before an arc marker.

    Legacy Equation Editor/MTEF conversions sometimes emit an arc as a
    postfix glyph, for example "B D ⌢". In math content this means the arc
    belongs above the preceding point sequence, not after it.
    """
    end = len(prefix)
    while end > 0 and prefix[end - 1].isspace():
        end -= 1
    pos = end
    chars: list[str] = []
    while pos > 0:
        while pos > 0 and prefix[pos - 1].isspace():
            pos -= 1
        if pos == 0:
            break
        ch = prefix[pos - 1]
        if not ("A" <= ch <= "Z"):
            break
        chars.append(ch)
        pos -= 1
    operand = "".join(reversed(chars))
    if len(operand) < 2:
        return prefix, ""
    return prefix[:pos], operand


def normalize_latex_notation(latex: str) -> str:
    if not latex:
        return latex
    markers = ("\\frown", "⌢", "�")
    out = ""
    index = 0
    while index < len(latex):
        found_marker = ""
        found_at = len(latex)
        for marker in markers:
            pos = latex.find(marker, index)
            if pos != -1 and pos < found_at:
                found_marker = marker
                found_at = pos
        if not found_marker:
            out += latex[index:]
            break
        out += latex[index:found_at]
        kept_prefix, operand = _take_arc_operand(out)
        if operand:
            out = kept_prefix + f"\\overset{{\\frown}}{{{operand}}}"
        else:
            out += found_marker
        index = found_at + len(found_marker)
    return out


@dataclass(frozen=True)
class FormulaToken:
    source: str
    latex: str
    formula_id: str = ""
    status: str = ""
    mathml: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "latex", normalize_latex_notation(self.latex))

    @property
    def markdown(self) -> str:
        return f"${self.latex}$" if self.latex else ""


class OmmlLatexProvider:
    """Small OMML AST visitor for common Word math nodes.

    This is intentionally a provider rather than inline pipeline code. The
    native ingest pipeline asks for a formula token; it should not know every
    OMML node shape.
    """

    def __init__(self) -> None:
        self.handlers = {
            "oMath": self._children,
            "oMathPara": self._children,
            "e": self._children,
            "num": self._children,
            "den": self._children,
            "deg": self._children,
            "sub": self._children,
            "sup": self._children,
            "r": self._run,
            "t": self._text,
            "sSup": self._sup,
            "sSub": self._sub,
            "sSubSup": self._subsup,
            "f": self._frac,
            "rad": self._rad,
            "d": self._delimiter,
            "nary": self._nary,
            "bar": self._bar,
            "acc": self._acc,
            "eqArr": self._eq_array,
            "groupChr": self._group_chr,
        }

    def token(self, el: ET.Element) -> FormulaToken:
        return FormulaToken(source="omml", latex=self.serialize(el), status="omml_latex_ok")

    def serialize(self, el: ET.Element | None) -> str:
        if el is None:
            return ""
        handler = self.handlers.get(lname(el), self._children)
        return handler(el).strip()

    def _children(self, el: ET.Element) -> str:
        return "".join(self.serialize(item) for item in list(el))

    def _run(self, el: ET.Element) -> str:
        return omml_text(el)

    def _text(self, el: ET.Element) -> str:
        return el.text or ""

    def _sup(self, el: ET.Element) -> str:
        return f"{self.serialize(child(el, 'e'))}^{{{self.serialize(child(el, 'sup'))}}}"

    def _sub(self, el: ET.Element) -> str:
        return f"{self.serialize(child(el, 'e'))}_{{{self.serialize(child(el, 'sub'))}}}"

    def _subsup(self, el: ET.Element) -> str:
        base = self.serialize(child(el, "e"))
        sub = self.serialize(child(el, "sub"))
        sup = self.serialize(child(el, "sup"))
        return f"{base}_{{{sub}}}^{{{sup}}}"

    def _frac(self, el: ET.Element) -> str:
        return f"\\frac{{{self.serialize(child(el, 'num'))}}}{{{self.serialize(child(el, 'den'))}}}"

    def _rad(self, el: ET.Element) -> str:
        deg = self.serialize(child(el, "deg"))
        body = self.serialize(child(el, "e"))
        return f"\\sqrt[{deg}]{{{body}}}" if deg else f"\\sqrt{{{body}}}"

    def _delimiter(self, el: ET.Element) -> str:
        props = child(el, "dPr")
        beg = attr_val(props.find("m:begChr", NS) if props is not None else None, "(")
        end = attr_val(props.find("m:endChr", NS) if props is not None else None, ")")
        return f"\\left{beg}{self.serialize(child(el, 'e'))}\\right{end}"

    def _nary(self, el: ET.Element) -> str:
        props = child(el, "naryPr")
        symbol = attr_val(props.find("m:chr", NS) if props is not None else None, "∑")
        op = {"∑": "\\sum", "∏": "\\prod", "∫": "\\int"}.get(symbol, symbol)
        sub = self.serialize(child(el, "sub"))
        sup = self.serialize(child(el, "sup"))
        limits = (f"_{{{sub}}}" if sub else "") + (f"^{{{sup}}}" if sup else "")
        return f"{op}{limits} {self.serialize(child(el, 'e'))}".strip()

    def _bar(self, el: ET.Element) -> str:
        return f"\\overline{{{self.serialize(child(el, 'e'))}}}"

    def _acc(self, el: ET.Element) -> str:
        return f"\\hat{{{self.serialize(child(el, 'e'))}}}"

    def _eq_array(self, el: ET.Element) -> str:
        lines = [self.serialize(item) for item in el.findall("m:e", NS)]
        return r" \\ ".join(line for line in lines if line)

    def _group_chr(self, el: ET.Element) -> str:
        return f"\\overbrace{{{self.serialize(child(el, 'e'))}}}"


class LegacyMtefManifestProvider:
    """Rehydrates legacy Equation Editor formulas from an existing MTEF manifest."""

    def __init__(self, manifest_path: Path | None = None) -> None:
        self.by_ole_rid: dict[str, dict[str, Any]] = {}
        self.manifest_path = manifest_path
        if manifest_path and manifest_path.exists():
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            for formula in data.get("formulas", []):
                rid = str(formula.get("ole_rid") or "")
                if formula.get("source") == "legacy_equation_mtef" and rid:
                    self.by_ole_rid[rid] = formula

    def token_for_run(self, run: ET.Element) -> FormulaToken | None:
        ole = run.find(".//o:OLEObject", NS)
        if ole is None:
            return None
        rid = ole.attrib.get(qn("r", "id"), "")
        formula = self.by_ole_rid.get(rid)
        if not formula:
            return FormulaToken(source="legacy_equation_mtef", latex="", formula_id="", status="mtef_missing_manifest")
        return FormulaToken(
            source="legacy_equation_mtef",
            latex=str(formula.get("latex") or ""),
            formula_id=str(formula.get("formula_id") or ""),
            status=str(formula.get("status") or ""),
            mathml=str(formula.get("mathml") or ""),
        )

    @property
    def converted_count(self) -> int:
        return len(self.by_ole_rid)
