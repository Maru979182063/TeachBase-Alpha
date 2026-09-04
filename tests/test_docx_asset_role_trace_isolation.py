"""中文说明：复用图片的不同出现位置必须各自保存模型调用证据。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from tools import docx_asset_role_visual_tagger_v01 as tagger


def test_reused_image_occurrences_keep_separate_traces(tmp_path, monkeypatch) -> None:
    # 中文说明：模型替身只提供合法结构，不参与图片语义判断；并发验证真实文件写入。
    image_path = tmp_path / "shared.png"
    image_path.write_bytes(b"image-placeholder")
    blocks = [
        {
            "block_id": f"b_{index:06d}",
            "source_order": index,
            "text": f"context-{index}",
            "image_refs": [{"asset_id": "shared_image", "storage_key": str(image_path)}],
        }
        for index in (1, 2)
    ]
    assets = tagger.build_assets(blocks, {})

    def fake_model(**kwargs):
        asset = kwargs["asset"]
        parsed = {
            "asset_id": asset["asset_id"],
            "block_id": asset["block_id"],
            "asset_role": "section_title_image",
            "target_field": "context",
            "confidence": 1.0,
            "needs_resolution": False,
        }
        return {"parsed": parsed, "raw_response": parsed, "raw_content": json.dumps(parsed)}

    monkeypatch.setattr(tagger, "call_model", fake_model)
    raw_dir = tmp_path / "raw"

    def process(asset):
        return tagger.tag_one(
            asset=asset, config={}, system_prompt="test", raw_dir=raw_dir,
            api_key="test-placeholder", timeout=1, attempts=1,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(process, assets))
    assert all(not issues for _, issues in results)

    def payloads(suffix: str) -> list[dict]:
        return [json.loads(path.read_text(encoding="utf-8")) for path in raw_dir.glob(suffix)]

    prompts = payloads("*.prompt.json")
    responses = payloads("*.response.json")
    contents = payloads("*.content.json")
    assert len(prompts) == len(responses) == len(contents) == 2
    expected = {"b_000001", "b_000002"}
    assert {item["asset"]["block_id"] for item in prompts} == expected
    assert {item["block_id"] for item in responses} == expected
    assert {item["block_id"] for item in contents} == expected
