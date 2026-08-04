from pathlib import Path

import json
import sys
import urllib.error


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import docx_native_text_repair_model_node_v01 as repair


def test_strip_json_content_accepts_fenced_recorded_response() -> None:
    raw = '```json\n{"question_id":"q1","repaired_display_markdown":"$x^2$"}\n```'

    parsed = json.loads(repair.strip_json_content(raw))

    assert parsed["question_id"] == "q1"
    assert parsed["repaired_display_markdown"] == "$x^2$"


def test_missing_fields_and_invalid_json_remain_reviewable() -> None:
    missing_fields = json.loads(repair.strip_json_content('{"question_id":"q1"}'))

    assert "repaired_display_markdown" not in missing_fields
    try:
        json.loads(repair.strip_json_content('{"question_id": '))
    except json.JSONDecodeError as exc:
        assert exc.msg
    else:
        raise AssertionError("invalid model JSON must not parse silently")


def test_validate_repair_preserves_asset_placeholders_and_flags_broken_latex() -> None:
    question = {
        "question_id": "q1",
        "asset_ids": ["docx_media_0001"],
        "display_markdown": "Stem ![docx_media_0001](asset://docx_media_0001) $x$",
    }

    issues = repair.validate_repair(question, "Stem without asset $x$")
    assert {"type": "asset_missing", "asset_id": "docx_media_0001"} in issues
    assert any(item["type"] == "asset_token_count_changed" for item in issues)

    latex_issues = repair.validate_repair(question, "Stem ![docx_media_0001](asset://docx_media_0001) $a___b$")
    assert any(item["type"] == "blank_underline_inside_math" for item in latex_issues)


def test_build_prompt_does_not_call_model_or_change_question_shape() -> None:
    question = {
        "question_id": "q1",
        "asset_ids": ["docx_media_0001"],
        "display_markdown": "Find $x$.",
        "model_segmentation": {"start_paragraph_index": 0, "end_paragraph_index": 0},
    }

    prompt = repair.build_prompt(question)

    assert "q1" in prompt
    assert "asset_ids" in prompt
    assert "Find $x$." in prompt


def test_call_model_uses_retry_checkpoint_without_changing_payload(monkeypatch, tmp_path: Path) -> None:
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
                    "choices": [{"message": {"content": "{\"question_id\":\"q1\"}"}}],
                    "usage": {"total_tokens": 7},
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        assert timeout == 180
        if calls == 1:
            raise urllib.error.URLError("timed out")
        return FakeResponse()

    monkeypatch.setattr(repair.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(repair.time, "sleep", sleeps.append)

    checkpoint_path = tmp_path / "q1.model_call_checkpoint.json"
    result = repair.call_model("test-key", "test-model", "prompt", checkpoint_path=checkpoint_path)

    assert calls == 2
    assert sleeps == [1.0]
    assert result["raw_content"] == "{\"question_id\":\"q1\"}"
    assert result["usage"] == {"total_tokens": 7}
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["status"] == "succeeded"
    assert checkpoint["result"] == result

    def unexpected_urlopen(request, timeout):
        raise AssertionError("success checkpoint should skip network")

    monkeypatch.setattr(repair.urllib.request, "urlopen", unexpected_urlopen)
    assert repair.call_model("test-key", "test-model", "prompt", checkpoint_path=checkpoint_path) == result
