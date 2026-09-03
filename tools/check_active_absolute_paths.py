from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("src", "tools", "config", ".github", "java-backend")
SCAN_FILES = ("package.json",)
TEXT_SUFFIXES = {".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".json", ".yaml", ".yml", ".ps1", ".java", ".xml"}
ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[/\\](?:Users|Projects)(?:[/\\][^\"'\s]+)+|/(?:Users|home)/[^\"'\s]+)")
DETECTION_ONLY_FILES = {
    "src/teachbase/final_chains/jobs.py",
    "tools/check_active_absolute_paths.py",
    "tools/runtime_clean_reproduction_check.mjs",
    "tools/run_modularization_phase2b_gate.py",
    "tools/validate_cleanroom_hardening_manifest.py",
    "tools/validate_final_chain_batch_queue_report.py",
    "tools/validate_final_chain_orchestrator_handshake.py",
    "tools/validate_java_shell_contract.py",
}


def build_report() -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    scanned = 0
    for path in _active_files():
        scanned += 1
        relative = path.relative_to(ROOT).as_posix()
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), start=1):
            matches = ABSOLUTE_PATH.findall(line)
            if not matches or relative in DETECTION_ONLY_FILES:
                continue
            findings.append(
                {
                    "path": relative,
                    "line": line_number,
                    "matches": matches,
                }
            )
    return {
        "schema_version": "active_absolute_path_policy.v0.1",
        "status": "pass" if not findings else "fail",
        "active_absolute_path_count": len(findings),
        "scanned_file_count": scanned,
        "findings": findings,
        "excluded_detection_only_files": sorted(DETECTION_ONLY_FILES),
    }


def _active_files() -> list[Path]:
    paths: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = ROOT / root_name
        if root.is_dir():
            paths.extend(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES)
    paths.extend(ROOT / name for name in SCAN_FILES if (ROOT / name).is_file())
    return sorted(set(paths))


def main() -> int:
    report = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
