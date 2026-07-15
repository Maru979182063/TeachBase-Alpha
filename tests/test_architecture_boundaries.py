from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "teachbase"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def source_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def test_package_does_not_import_legacy_tools_or_runtime() -> None:
    for path in source_files(SRC):
        text = read(path)
        assert "from tools" not in text, path
        assert "import tools" not in text, path
        assert "runtime_backbone" not in text, path


def test_semantic_role_domain_does_not_depend_on_cli_or_environment() -> None:
    domain_files = [
        path
        for path in source_files(SRC / "semantic_role")
        if path.name not in {"cli.py", "__init__.py"}
    ]
    for path in domain_files:
        text = read(path)
        assert "argparse" not in text, path
        assert "os.environ" not in text, path


def test_metrics_are_pure_calculation_without_file_writes() -> None:
    text = read(SRC / "semantic_role" / "metrics.py")
    assert "write_json" not in text
    assert "write_text" not in text
    assert ".write_text" not in text
    assert ".open(" not in text


def test_review_pack_does_not_import_or_modify_evaluation_policy() -> None:
    text = read(SRC / "semantic_role" / "review_pack.py")
    assert "compute_metrics" not in text
    assert "dataset_coverage" not in text
    assert "case_result" not in text
    assert "SEMANTIC_ROLE_" not in text


def test_legacy_cli_wrapper_has_no_formal_metrics_calculation() -> None:
    text = read(ROOT / "tools" / "run_semantic_role_effectiveness_eval.py")
    assert "compute_metrics" not in text
    assert "dataset_coverage" not in text
    assert "confusion_matrix" not in text
    assert "critical_misroutes" not in text


def test_package_has_no_hardcoded_local_outputs_or_sys_path_hack() -> None:
    for path in source_files(SRC):
        text = read(path)
        normalized = text.replace("\\", "/")
        forbidden_outputs = [
            "outputs/english_text_first",
            "outputs/docx_native",
            "outputs/runtime",
            "outputs/pipeline_baseline_snapshot",
        ]
        for marker in forbidden_outputs:
            assert marker not in normalized, path
        assert "sys.path" not in text, path


def test_new_phase2a_tests_do_not_use_importlib_dynamic_loading() -> None:
    import_statement = "import " + "importlib"
    from_statement = "from " + "importlib"
    dynamic_loader = "spec_from_" + "file_location"
    for name in ["test_architecture_boundaries.py", "test_semantic_role_golden_parity.py"]:
        text = read(ROOT / "tests" / name)
        assert import_statement not in text
        assert from_statement not in text
        assert dynamic_loader not in text
