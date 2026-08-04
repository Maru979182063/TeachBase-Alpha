from __future__ import annotations

import sys
from pathlib import Path

import english_docx_child_skill_tagger_v01 as engine


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "english_docx_native_md" / "cloze_child_skill_tagger_v01.json"


def main() -> None:
    if "--config" not in sys.argv:
        sys.argv[1:1] = ["--config", str(DEFAULT_CONFIG)]
    engine.main()


if __name__ == "__main__":
    main()
