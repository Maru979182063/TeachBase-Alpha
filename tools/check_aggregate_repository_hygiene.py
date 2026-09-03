from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from teachbase.infrastructure.artifact_store import write_json

ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = ROOT / "artifacts" / "ci" / "aggregate_repository_hygiene.json"
SECRET_PATTERNS = {
    "ark_api_key": re.compile(r"ark-[A-Za-z0-9]{20,}"),
    "openai_style_key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
FINAL_CHAIN_DB_WRITE_FILES = (
    "src/teachbase/final_chains",
    "tools/final_chain_control.py",
    "tools/run_final_chain_ops_gate.py",
    "tools/build_final_chain_ops_health.py",
    "tools/build_pdf_english_graph_first_rebuild_smoke.py",
)


def build_report(base: str) -> dict[str, Any]:
    changed = _changed_paths(base)
    yaml_failures = _yaml_failures()
    secret_findings = _secret_findings(changed)
    large_files = _large_changed_files(changed)
    binary_files = _binary_changed_files(changed)
    direct_db_writes = _final_chain_direct_db_writes()
    temp_residue = _temporary_residue()
    checks = [
        {"name": "yaml_parses", "ok": not yaml_failures, "value": yaml_failures},
        {"name": "changed_files_contain_no_high_confidence_secrets", "ok": not secret_findings, "value": secret_findings},
        {"name": "changed_files_contain_no_large_unapproved_files", "ok": not large_files, "value": large_files},
        {"name": "changed_binary_files_are_approved_fixtures", "ok": not binary_files, "value": binary_files},
        {
            "name": "final_chain_python_node_do_not_write_canonical_postgres",
            "ok": not direct_db_writes,
            "value": direct_db_writes,
        },
        {"name": "temporary_artifact_residue_is_zero", "ok": not temp_residue, "value": temp_residue},
    ]
    return {
        "schema_version": "aggregate_repository_hygiene.v0.1",
        "status": "pass" if all(check["ok"] for check in checks) else "fail",
        "base": base,
        "changed_file_count": len(changed),
        "checks": checks,
    }


def _changed_paths(base: str) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", base, "--"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    return sorted(line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip())


def _yaml_failures() -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for root_name in ("config", ".github"):
        root = ROOT / root_name
        for path in sorted([*root.rglob("*.yaml"), *root.rglob("*.yml")]):
            try:
                yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            except (OSError, yaml.YAMLError) as exc:
                failures.append({"path": path.relative_to(ROOT).as_posix(), "error": type(exc).__name__})
    return failures


def _secret_findings(changed: list[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for relative in changed:
        path = ROOT / relative
        if not path.is_file() or path.suffix.lower() in {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".zip"}:
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append({"path": relative, "pattern": name})
    return findings


def _large_changed_files(changed: list[str]) -> list[dict[str, Any]]:
    return [
        {"path": relative, "size_bytes": (ROOT / relative).stat().st_size}
        for relative in changed
        if (ROOT / relative).is_file() and (ROOT / relative).stat().st_size > 5 * 1024 * 1024
    ]


def _binary_changed_files(changed: list[str]) -> list[str]:
    approved_prefixes = ("tests/fixtures/", "tests/goldens/")
    binary_suffixes = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".zip"}
    return [
        relative
        for relative in changed
        if (ROOT / relative).is_file()
        and (ROOT / relative).suffix.lower() in binary_suffixes
        and not relative.startswith(approved_prefixes)
    ]


def _final_chain_direct_db_writes() -> list[dict[str, Any]]:
    pattern = re.compile(r"\b(?:insert\s+into|update|delete\s+from)\s+teachbase_app\.", re.IGNORECASE)
    findings: list[dict[str, Any]] = []
    paths: list[Path] = []
    for value in FINAL_CHAIN_DB_WRITE_FILES:
        path = ROOT / value
        if path.is_dir():
            paths.extend(item for item in path.rglob("*") if item.suffix.lower() in {".py", ".js", ".mjs"})
        elif path.is_file():
            paths.append(path)
    for path in sorted(set(paths)):
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), start=1):
            if pattern.search(line):
                findings.append({"path": path.relative_to(ROOT).as_posix(), "line": line_number})
    return findings


def _temporary_residue() -> list[str]:
    findings: list[str] = []
    for root_name in ("outputs", "artifacts"):
        root = ROOT / root_name
        if not root.exists():
            continue
        findings.extend(
            path.relative_to(ROOT).as_posix()
            for path in root.rglob("*")
            if path.is_file() and (path.name.endswith(".tmp") or path.name.startswith(".tmp"))
        )
    return sorted(findings)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run aggregate PR hygiene checks without executing production pipelines.")
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    report = build_report(args.base)
    write_json(REPORT_JSON, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
