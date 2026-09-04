"""中文说明：防止数学 DOCX 主链只提交入口、漏收运行配置和提示词。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CONFIGS = (
    "docx_native_block_tagger_v01.yaml",
    "docx_asset_role_visual_tagger_v01.yaml",
    "docx_question_boundary_cutter_v01.yaml",
    "docx_question_complexity_router_v01.yaml",
    "docx_question_part_normalizer_v01.yaml",
    "docx_question_part_long_normalizer_v01.yaml",
    "docx_question_part_twostage_probe_v01.yaml",
    "docx_math_question_refiner_v01.yaml",
    "docx_math_long_composite_refiner_v01.yaml",
    "docx_math_span_patch_refiner_v01.yaml",
    "docx_math_long_packet_assembler_v01.yaml",
)


def test_math_runtime_configs_and_referenced_inputs_exist() -> None:
    # 中文说明：仅验证显式文件契约，不判断教学语义，也不执行付费模型调用。
    missing: list[str] = []

    def inspect(value: object, origin: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, str) and (
                    key.endswith("prompt_path")
                    or key.endswith("schema_path")
                    or key == "entrypoint"
                ):
                    target = ROOT / item
                    if not target.is_file() or target.stat().st_size == 0:
                        missing.append(f"{origin}: {key} -> {item}")
                else:
                    inspect(item, origin)
        elif isinstance(value, list):
            for item in value:
                inspect(item, origin)

    for name in RUNTIME_CONFIGS:
        path = ROOT / "config" / name
        if not path.is_file():
            missing.append(f"config/{name}")
            continue
        inspect(json.loads(path.read_text(encoding="utf-8")), name)

    assert not missing, "Missing math runtime inputs:\n" + "\n".join(missing)


@pytest.mark.parametrize("entrypoint", [
    "docx_math_question_refiner_v01.py",
    "docx_math_long_composite_refiner_v01.py",
    "docx_math_span_patch_refiner_v01.py",
])
def test_refiner_cli_imports_without_model_calls(entrypoint: str) -> None:
    # 中文说明：真实启动参数解析，捕获遗漏的 Python 包和本地辅助模块；--help 不调用模型。
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / entrypoint), "--help"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    assert result.returncode == 0, result.stderr
