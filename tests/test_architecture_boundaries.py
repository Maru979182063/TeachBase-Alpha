from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "teachbase"

# Explicit exceptions:
# - `src/teachbase/semantic_role/cli.py` is the package CLI facade and may import argparse.
# - `src/teachbase/infrastructure/*` owns filesystem writes.
# - `semantic_role/evaluator.py`, `candidate_manifest.py`, and `review_pack.py`
#   are Phase 2A application/adapters that write declared artifacts.
# - Legacy wrappers under `tools/` may import legacy modules; package code may not.
ARGPARSE_ALLOWED = {SRC / "semantic_role" / "cli.py"}
WRITE_ALLOWED = {
    SRC / "infrastructure" / "artifact_store.py",
    SRC / "semantic_role" / "evaluator.py",
    SRC / "semantic_role" / "candidate_manifest.py",
    SRC / "semantic_role" / "review_pack.py",
}


def source_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported_modules(node: ast.AST) -> set[str]:
    modules: set[str] = set()
    for item in ast.walk(node):
        if isinstance(item, ast.Import):
            modules.update(alias.name for alias in item.names)
        elif isinstance(item, ast.ImportFrom) and item.module:
            modules.add(item.module)
    return modules


def calls_named(node: ast.AST, names: set[str]) -> bool:
    for item in ast.walk(node):
        if isinstance(item, ast.Call):
            func = item.func
            if isinstance(func, ast.Name) and func.id in names:
                return True
            if isinstance(func, ast.Attribute) and func.attr in names:
                return True
    return False


def reads_environment(node: ast.AST) -> bool:
    for item in ast.walk(node):
        if isinstance(item, ast.Attribute) and item.attr == "environ":
            if isinstance(item.value, ast.Name) and item.value.id == "os":
                return True
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute):
            if item.func.attr == "getenv" and isinstance(item.func.value, ast.Name) and item.func.value.id == "os":
                return True
    return False


def test_package_ast_does_not_import_legacy_tools_or_runtime() -> None:
    for path in source_files(SRC):
        modules = imported_modules(tree(path))
        assert not any(name == "tools" or name.startswith("tools.") for name in modules), path
        assert not any("runtime_backbone" in name for name in modules), path


def test_domain_application_ast_does_not_import_argparse_except_cli_facade() -> None:
    for path in source_files(SRC / "semantic_role"):
        if path in ARGPARSE_ALLOWED:
            continue
        assert "argparse" not in imported_modules(tree(path)), path


def test_domain_ast_does_not_read_environment_or_write_files_directly() -> None:
    for path in source_files(SRC / "semantic_role"):
        node = tree(path)
        assert not reads_environment(node), path
        if path not in WRITE_ALLOWED:
            assert not calls_named(node, {"open", "write_text", "write_bytes", "write_json", "write"}), path


def test_metrics_are_pure_calculation_without_artifact_writes() -> None:
    node = tree(SRC / "semantic_role" / "metrics.py")
    modules = imported_modules(node)
    assert "teachbase.infrastructure.artifact_store" not in modules
    assert not calls_named(node, {"open", "write_text", "write_bytes", "write_json", "write"})


def test_review_pack_does_not_import_or_modify_evaluation_policy() -> None:
    modules = imported_modules(tree(SRC / "semantic_role" / "review_pack.py"))
    assert "teachbase.semantic_role.metrics" not in modules
    assert "teachbase.semantic_role.evaluator" not in modules


def test_legacy_cli_wrapper_has_no_formal_metrics_calculation() -> None:
    modules = imported_modules(tree(ROOT / "tools" / "run_semantic_role_effectiveness_eval.py"))
    assert "teachbase.semantic_role.metrics" not in modules


def test_package_has_no_new_sys_path_hack_or_disallowed_dynamic_loading() -> None:
    for path in source_files(SRC):
        node = tree(path)
        modules = imported_modules(node)
        assert "sys" not in modules, path
        assert "importlib" not in modules, path
        assert not calls_named(node, {"spec_from_file_location"}), path
