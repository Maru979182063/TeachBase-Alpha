from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


IGNORED_FIELD_NAMES = {
    "created_at",
    "started_at",
    "finished_at",
    "run_id",
}
RANDOM_REQUEST_KEYS = {"request_id"}
PATH_LIKE_KEYS = {"path", "output_root", "run_root", "pdf_path"}


def _is_explicit_random_request_id(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    # Keep this deliberately narrow. Deterministic fixture ids stay strict.
    return len(value) >= 16 and any(ch.isdigit() for ch in value) and any(ch.isalpha() for ch in value)


def _normalize_path_string(value: str, roots: list[Path]) -> str:
    normalized = value.replace("\\", "/")
    for root in roots:
        root_text = str(root.resolve()).replace("\\", "/")
        if root_text and normalized.startswith(root_text):
            return "<ABS_ROOT>" + normalized[len(root_text) :]
    temp_markers = ["/Temp/", "/tmp/", "/AppData/Local/Temp/"]
    for marker in temp_markers:
        idx = normalized.find(marker)
        if idx >= 0:
            return "<TEMP_ROOT>" + normalized[idx + len(marker) :]
    return normalized


def canonicalize(value: Any, *, roots: list[Path] | None = None) -> tuple[Any, int]:
    roots = roots or []
    ignored = 0

    def walk(obj: Any, key: str | None = None) -> Any:
        nonlocal ignored
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for raw_key, raw_value in sorted(obj.items(), key=lambda item: str(item[0])):
                k = str(raw_key)
                if k in IGNORED_FIELD_NAMES:
                    ignored += 1
                    continue
                if k in RANDOM_REQUEST_KEYS and _is_explicit_random_request_id(raw_value):
                    ignored += 1
                    continue
                out[k] = walk(raw_value, k)
            return out
        if isinstance(obj, list):
            return [walk(item, key) for item in obj]
        if isinstance(obj, str) and key in PATH_LIKE_KEYS:
            normalized = _normalize_path_string(obj, roots)
            if normalized != obj:
                ignored += 1
            return normalized
        return obj

    return walk(copy.deepcopy(value)), ignored


def canonical_json_bytes(value: Any, *, roots: list[Path] | None = None) -> tuple[bytes, int]:
    canonical, ignored = canonicalize(value, roots=roots)
    return json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"), ignored


def canonical_hash(value: Any, *, roots: list[Path] | None = None) -> tuple[str, int]:
    payload, ignored = canonical_json_bytes(value, roots=roots)
    return hashlib.sha256(payload).hexdigest(), ignored


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _json_paths(left: Any, right: Any, prefix: str = "$", limit: int = 50) -> list[str]:
    if limit <= 0:
        return []
    if type(left) is not type(right):
        return [prefix]
    if isinstance(left, dict):
        paths: list[str] = []
        keys = sorted(set(left) | set(right))
        for key in keys:
            if key not in left or key not in right:
                paths.append(f"{prefix}.{key}")
            else:
                paths.extend(_json_paths(left[key], right[key], f"{prefix}.{key}", limit - len(paths)))
            if len(paths) >= limit:
                return paths[:limit]
        return paths
    if isinstance(left, list):
        paths = []
        max_len = max(len(left), len(right))
        for idx in range(max_len):
            if idx >= len(left) or idx >= len(right):
                paths.append(f"{prefix}[{idx}]")
            else:
                paths.extend(_json_paths(left[idx], right[idx], f"{prefix}[{idx}]", limit - len(paths)))
            if len(paths) >= limit:
                return paths[:limit]
        return paths
    return [] if left == right else [prefix]


def compare_json_files(baseline_path: Path, current_path: Path, *, roots: list[Path] | None = None) -> dict[str, Any]:
    baseline = load_json(baseline_path)
    current = load_json(current_path)
    baseline_canonical, ignored_left = canonicalize(baseline, roots=roots)
    current_canonical, ignored_right = canonicalize(current, roots=roots)
    baseline_bytes = json.dumps(baseline_canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    current_bytes = json.dumps(current_canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    baseline_hash = hashlib.sha256(baseline_bytes).hexdigest()
    current_hash = hashlib.sha256(current_bytes).hexdigest()
    equality = baseline_hash == current_hash
    mismatch_paths = [] if equality else _json_paths(baseline_canonical, current_canonical)
    return {
        "baseline_path": str(baseline_path),
        "current_path": str(current_path),
        "baseline_hash": baseline_hash,
        "current_hash": current_hash,
        "canonical_hash": baseline_hash if equality else "",
        "equality": equality,
        "mismatch_json_paths": mismatch_paths,
        "mismatch_reason": "" if equality else "canonical_hash_mismatch",
        "ignored_field_count": ignored_left + ignored_right,
    }


def compare_artifact_sets(
    baseline_root: Path,
    current_root: Path,
    artifacts: list[str],
    *,
    roots: list[Path] | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for rel in artifacts:
        baseline_path = baseline_root / rel
        current_path = current_root / rel
        if not baseline_path.exists() or not current_path.exists():
            errors.append(f"missing_artifact:{rel}")
            results.append(
                {
                    "artifact": rel,
                    "baseline_path": str(baseline_path),
                    "current_path": str(current_path),
                    "baseline_hash": "",
                    "current_hash": "",
                    "canonical_hash": "",
                    "equality": False,
                    "mismatch_json_paths": ["$"],
                    "mismatch_reason": "missing_artifact",
                    "ignored_field_count": 0,
                }
            )
            continue
        item = compare_json_files(baseline_path, current_path, roots=roots)
        item["artifact"] = rel
        results.append(item)
    equality = bool(results) and all(item["equality"] for item in results)
    mismatch_paths = [f"{item['artifact']}:{path}" for item in results for path in item["mismatch_json_paths"]]
    return {
        "schema_version": "semantic_shadow_non_interference_report.v0.1",
        "baseline_root": str(baseline_root),
        "current_root": str(current_root),
        "compared_artifact_count": len(results),
        "ignored_field_count": sum(int(item["ignored_field_count"]) for item in results),
        "equality": equality,
        "baseline_hash": hashlib.sha256("|".join(item["baseline_hash"] for item in results).encode("utf-8")).hexdigest(),
        "current_hash": hashlib.sha256("|".join(item["current_hash"] for item in results).encode("utf-8")).hexdigest(),
        "canonical_hash": hashlib.sha256("|".join(item["canonical_hash"] for item in results).encode("utf-8")).hexdigest()
        if equality
        else "",
        "mismatch_json_paths": mismatch_paths,
        "mismatch_reason": "" if equality else ";".join(errors) or "artifact_canonical_mismatch",
        "artifacts": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Canonical-compare Semantic Shadow baseline artifacts.")
    parser.add_argument("--baseline-root", required=True)
    parser.add_argument("--current-root", required=True)
    parser.add_argument("--artifact", action="append", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    baseline_root = Path(args.baseline_root)
    current_root = Path(args.current_root)
    report = compare_artifact_sets(
        baseline_root,
        current_root,
        list(args.artifact),
        roots=[Path.cwd(), baseline_root, current_root],
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["equality"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
