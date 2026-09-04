"""中文说明：边界组装应尊重模型上下文判定，并对冲突保持阻断。"""

from tools import docx_question_boundary_cutter_v01 as cutter


def window(wid, ids, context=(), starts=(), continuation=()):
    return {
        "window_id": wid,
        "payload": {"current_blocks": [{"block_id": bid} for bid in ids]},
        "parsed": {
            "context_only_blocks": [{"block_ids": list(context), "evidence": "model evidence"}],
            "new_question_starts": [{"block_id": bid} for bid in starts],
            "continuation_groups": [{"block_ids": list(continuation)}],
        },
    }


def assemble(results):
    ids = ["b_000000", "b_000001", "b_000002"]
    disposition = cutter.resolve_context_dispositions(results)
    packet = cutter.assemble_packets(
        [{"block_id": bid} for bid in ids],
        {bid: {"primary_role": "question_content"} for bid in ids},
        {}, [{"block_id": "b_000001"}], disposition,
    )
    return packet, disposition


def test_explicit_context_is_preserved_outside_question_body():
    packet, disposition = assemble([
        window("c_0", ["b_000000", "b_000001", "b_000002"], context=["b_000000"], starts=["b_000001"], continuation=["b_000002"]),
    ])
    assert packet["unassigned_candidate_blocks"] == []
    assert packet["context_only_blocks"] == ["b_000000"]
    assert packet["packets"][0]["source_block_ids"] == ["b_000001", "b_000002"]
    assert disposition["decisions"][0]["votes"][0]["context_evidence"] == ["model evidence"]


def test_conflicting_context_and_question_votes_remain_blocking():
    packet, disposition = assemble([
        window("c_0", ["b_000000"], context=["b_000000"]),
        window("c_1", ["b_000000"], starts=["b_000000"]),
    ])
    assert disposition["conflicting_block_ids"] == ["b_000000"]
    assert packet["unassigned_candidate_blocks"] == ["b_000000"]
    assert packet["context_only_blocks"] == []


def test_missing_current_vote_does_not_silently_exclude_content():
    packet, _ = assemble([
        window("c_0", ["b_000000"], context=["b_000000"]),
        window("c_1", ["b_000000"]),
    ])
    assert packet["unassigned_candidate_blocks"] == ["b_000000"]


def test_noncurrent_context_vote_cannot_remove_question_content():
    packet, disposition = assemble([
        window("c_0", ["b_000001"], context=["b_000000"], starts=["b_000001"]),
    ])
    assert disposition["context_only_block_ids"] == []
    assert packet["unassigned_candidate_blocks"] == ["b_000000"]


def test_accounting_only_requires_current_candidates(tmp_path, monkeypatch):
    # 中文说明：用保存的模型结果重放，确保参考段落不会产生虚假的漏答警告。
    import json

    payload = {"core_block_ids": ["b_000000", "b_000001"], "current_blocks": [{"block_id": "b_000001"}]}
    monkeypatch.setattr(cutter, "build_window_payload", lambda **kwargs: payload)
    (tmp_path / "c_0.response.json").write_text("{}", encoding="utf-8")
    (tmp_path / "c_0.parsed.json").write_text(json.dumps({"new_question_starts": [{"block_id": "b_000001"}]}), encoding="utf-8")
    from types import SimpleNamespace

    result = cutter.run_one_window(
        window=SimpleNamespace(window_id="c_0"), blocks=[], tags={}, config={},
        doc_id="test", system_prompt="", user_template="", api_key="", raw_dir=tmp_path,
        timeout=1, max_attempts=1, no_resume=False,
    )
    assert result["source"] == "resume"
    assert result["issues"] == []
