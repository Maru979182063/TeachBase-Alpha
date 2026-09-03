from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import teacher_handout_visual_transcribe_doubao as visual_runtime
import visual_transcription_pipeline as visual_pipeline


def test_run_raw_transcription_node_passes_checkpoint_path_when_supported(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def model_fn(api_key, model_name, prompt, image_paths, *, checkpoint_path=None):
        seen["api_key"] = api_key
        seen["model_name"] = model_name
        seen["prompt"] = prompt
        seen["image_paths"] = image_paths
        seen["checkpoint_path"] = checkpoint_path
        return {"raw_content": "{}"}

    checkpoint_path = tmp_path / "checkpoint.json"
    result = visual_pipeline.run_raw_transcription_node(
        api_key="key",
        model_name="model",
        prompt="prompt",
        image_paths=["a.png"],
        call_model_fn=model_fn,
        checkpoint_path=checkpoint_path,
    )

    assert result == {"raw_content": "{}"}
    assert seen["checkpoint_path"] == checkpoint_path
    assert [str(path) for path in seen["image_paths"]] == ["a.png"]


def test_run_raw_transcription_node_keeps_legacy_model_fn_compatible(tmp_path: Path) -> None:
    def legacy_model_fn(api_key, model_name, prompt, image_paths):
        return {
            "api_key": api_key,
            "model_name": model_name,
            "prompt": prompt,
            "image_count": len(image_paths),
        }

    result = visual_pipeline.run_raw_transcription_node(
        api_key="key",
        model_name="model",
        prompt="prompt",
        image_paths=["a.png", "b.png"],
        call_model_fn=legacy_model_fn,
        checkpoint_path=tmp_path / "unused.json",
    )

    assert result == {"api_key": "key", "model_name": "model", "prompt": "prompt", "image_count": 2}


def test_visual_runtime_model_call_uses_retry_checkpoint(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"not-a-real-image-but-ok-for-base64")
    calls = 0
    sleeps: list[float] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [{"message": {"content": "{\"visible_blocks\":[]}"}}],
                    "usage": {"total_tokens": 11},
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        assert timeout == 180
        if calls == 1:
            raise urllib.error.URLError("EOF while reading response")
        return FakeResponse()

    monkeypatch.setattr(visual_runtime.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(visual_runtime.time, "sleep", sleeps.append)

    checkpoint_path = tmp_path / "raw_blocks.model_call_checkpoint.json"
    result = visual_runtime.call_raw_blocks_model(
        "test-key",
        "test-model",
        "prompt",
        [image_path],
        checkpoint_path=checkpoint_path,
    )

    assert calls == 2
    assert sleeps == [1.0]
    assert result["raw_content"] == "{\"visible_blocks\":[]}"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["status"] == "succeeded"
    assert checkpoint["result"] == result
    assert checkpoint["metadata"]["node"] == "raw_blocks_model_node"

    def unexpected_urlopen(request, timeout):
        raise AssertionError("success checkpoint should skip network")

    monkeypatch.setattr(visual_runtime.urllib.request, "urlopen", unexpected_urlopen)
    assert (
        visual_runtime.call_raw_blocks_model(
            "test-key",
            "test-model",
            "prompt",
            [image_path],
            checkpoint_path=checkpoint_path,
        )
        == result
    )
