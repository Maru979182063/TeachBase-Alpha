from __future__ import annotations

import importlib.util
import inspect
import sys
import tempfile
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_FILES = [
    ROOT / "tests" / "test_document_profile_resolver_contract.py",
    ROOT / "tests" / "test_semantic_role_adapter_contract.py",
    ROOT / "tests" / "test_semantic_role_adapter_golden_cases.py",
    ROOT / "tests" / "test_semantic_role_adapter_shadow_diff.py",
]


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot_load_test_module:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    passed = 0
    failed = 0
    for path in TEST_FILES:
        module = _load_module(path)
        for name, fn in sorted(vars(module).items()):
            if not name.startswith("test_") or not callable(fn):
                continue
            try:
                sig = inspect.signature(fn)
                kwargs = {}
                if "tmp_path" in sig.parameters:
                    with tempfile.TemporaryDirectory() as td:
                        kwargs["tmp_path"] = Path(td)
                        fn(**kwargs)
                else:
                    fn()
                passed += 1
                print(f"PASS {path.name}::{name}")
            except Exception:
                failed += 1
                print(f"FAIL {path.name}::{name}")
                traceback.print_exc()
    print(f"semantic_role_shadow_tests passed={passed} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

