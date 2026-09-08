"""G0 身份矩阵：验证纯合同，不伪装成持久化接收或 HTTP 验收。"""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("delivery_contract", ROOT / "tools/candidate_delivery_contract.py")
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
FIXTURES = ROOT / "tests/fixtures/candidate_delivery"


def load(name="one-shot"):
    return json.loads((FIXTURES / (name + ".json")).read_text(encoding="utf-8"))


def stable():
    return load("registered-stable-test-only"), load("test-only-authorities")


def result(manifest, registry=None):
    return contract.validate_manifest(manifest, registry)


def test_one_shot_explicit_and_side_effect_free():
    m = load()
    before = copy.deepcopy(m)
    r = result(m)
    assert m == before
    assert m["questions"][0]["identity"]["stableQuestionKey"] is None
    assert r["questions"][0]["identityMode"] == "one_shot_candidate"
    assert not r["databaseWritten"] and not r["assetBytesVerified"] and not r["durableReceiptImplemented"]


def test_same_request_same_manifest_same_digest_and_identity():
    a = load()
    assert result(a) == result(copy.deepcopy(a))


def test_same_request_changed_body_has_different_digest():
    a = load(); b = copy.deepcopy(a)
    b["questions"][0]["content"]["answerMarkdown"] = "B"
    assert a["importRequestId"] == b["importRequestId"]
    assert result(a)["requestDigest"] != result(b)["requestDigest"]
    # 后续 G2 才会将已有 request ID 与该摘要绑定并验证 HTTP 409。


def test_new_request_same_delivery_retains_digest():
    a = load(); b = copy.deepcopy(a)
    b["importRequestId"] = "00000000-0000-4000-8000-000000000099"
    assert result(a) == result(b)


def test_new_package_one_shot_identity_is_new_even_if_content_identical():
    a = load(); b = copy.deepcopy(a)
    b["packageId"] = "00000000-0000-4000-8000-000000000099"
    ra, rb = result(a)["questions"][0], result(b)["questions"][0]
    assert ra["identityKey"] != rb["identityKey"]
    assert ra["contentHash"] == rb["contentHash"]


def test_one_shot_item_order_and_number_not_identity():
    a = load(); b = copy.deepcopy(a)
    b["questions"][0]["itemKey"] = "changed-display-order-999"
    assert result(a)["questions"][0]["identityKey"] == result(b)["questions"][0]["identityKey"]


def test_unregistered_stable_claim_rejected():
    m, _ = stable()
    with pytest.raises(contract.ContractError, match="stable_identity_contract_not_registered"):
        result(m)


def test_test_registered_external_key_is_not_derived_from_content_or_anchor():
    m, registry = stable()
    r = result(m, registry)
    assert r["questions"][0]["identityKey"][-1] == m["questions"][0]["identity"]["stableQuestionKey"]


def test_registered_profile_change_preserves_identity_and_content():
    a, registry = stable(); b = copy.deepcopy(a)
    b["pipeline"] = {"runId": "another-run", "profileVersion": "another-model"}
    b["packageId"] = "00000000-0000-4000-8000-000000000099"
    ra, rb = result(a, registry), result(b, registry)
    assert ra["questions"] == rb["questions"]
    assert ra["requestDigest"] != rb["requestDigest"]


def test_registered_content_change_retains_identity_changes_revision_digest():
    a, registry = stable(); b = copy.deepcopy(a)
    b["questions"][0]["content"]["stemMarkdown"] += " 新内容"
    ra, rb = result(a, registry)["questions"][0], result(b, registry)["questions"][0]
    assert ra["identityKey"] == rb["identityKey"]
    assert ra["contentHash"] != rb["contentHash"]


def test_identical_content_different_opaque_keys_not_merged():
    a, registry = stable(); b = copy.deepcopy(a)
    b["questions"][0]["identity"]["stableQuestionKey"] = "fixture-persisted-record-beta"
    b["questions"][0]["identity"]["anchorEvidence"]["persistentRecordId"] = "fixture-persisted-record-beta"
    ra, rb = result(a, registry)["questions"][0], result(b, registry)["questions"][0]
    assert ra["identityKey"] != rb["identityKey"] and ra["contentHash"] == rb["contentHash"]


def test_split_items_may_not_reuse_one_identity():
    m, registry = stable()
    second = copy.deepcopy(m["questions"][0]); second["itemKey"] = "another-local-item"
    m["questions"].append(second)
    with pytest.raises(contract.ContractError, match="duplicate_question_identity"):
        result(m, registry)


def test_workspace_scope_separates_identity():
    a, registry = stable(); b = copy.deepcopy(a)
    b["workspaceId"] = "00000000-0000-4000-8000-000000000099"
    assert result(a, registry)["questions"][0]["identityKey"] != result(b, registry)["questions"][0]["identityKey"]


def test_source_namespace_not_trusted_by_key_alone():
    m, registry = stable(); m["sourceSystem"] = "unregistered_other_source"
    with pytest.raises(contract.ContractError, match="stable_identity_contract_not_registered"):
        result(m, registry)


@pytest.mark.parametrize("mutation,code", [
    (lambda m: m.update(manifestSchemaVersion=2), "schema_invalid"),
    (lambda m: m.update(reviewStatus="approved"), "schema_invalid"),
    (lambda m: m["questions"][0]["identity"].update(stableQuestionKey="guessed"), "schema_invalid"),
    (lambda m: m["questions"][0].update(contentHash="0" * 64), "content_hash_mismatch"),
    (lambda m: m["questions"][0].update(sourceDocumentKey="missing"), "source_document_unresolved"),
    (lambda m: m["files"][0].update(path="../escape"), "package_path_invalid"),
    (lambda m: m["files"][0].update(path="C:/escape"), "package_path_invalid"),
    (lambda m: m["files"][0].update(path="https://example.invalid/x"), "package_path_invalid"),
    (lambda m: m["files"][0].update(sizeBytes=1.5), "schema_invalid"),
])
def test_contract_rejections(mutation, code):
    m = load(); mutation(m)
    with pytest.raises(contract.ContractError, match=code):
        result(m)


def test_registered_anchor_fields_and_document_required():
    m, registry = stable(); m["questions"][0]["identity"]["anchorEvidence"] = {"pageNumber": "42"}
    with pytest.raises(contract.ContractError, match="stable_anchor_fields_mismatch"):
        result(m, registry)
    m, registry = stable(); m["sourceDocuments"][0]["documentStableKey"] = None
    with pytest.raises(contract.ContractError, match="document_stable_key_required"):
        result(m, registry)


def test_provenance_and_classification_not_content_digest():
    a = load(); b = copy.deepcopy(a)
    b["questions"][0]["sourceEvidence"]["pageNumbers"] = [2]
    b["questions"][0]["classificationSuggestions"]["grade"] = "高一"
    assert result(a)["questions"] == result(b)["questions"]
    assert result(a)["requestDigest"] != result(b)["requestDigest"]


def test_canonical_golden_unicode_math_and_object_order():
    expected = '{"a":"集合 \\n","z":[1,true,null],"公式":"\\\\textcircled{1}"}'.encode("utf-8")
    assert contract.canonical_bytes({"公式": r"\textcircled{1}", "z": [1, True, None], "a": "集合 \n"}) == expected
    m = load(); reordered = dict(reversed(list(m.items())))
    assert result(m) == result(reordered)
    m["questions"][0]["contentHash"] = contract.content_hash(m["questions"][0])
    result(m)


def test_duplicate_json_member_rejected(tmp_path):
    file = tmp_path / "duplicate.json"; file.write_text('{"a":1,"a":2}', encoding="utf-8")
    with pytest.raises(contract.ContractError, match="duplicate_json_member"):
        contract.load_manifest(file)


def test_registered_contract_version_change_needs_explicit_registration():
    m, registry = stable(); before = result(m, registry)["questions"]
    m["questions"][0]["identity"]["identityContractVersion"] = 2
    with pytest.raises(contract.ContractError, match="stable_identity_contract_not_registered"):
        result(m, registry)
    next_version = copy.deepcopy(registry["contracts"][0]); next_version["identityContractVersion"] = 2
    registry["contracts"].append(next_version)
    assert result(m, registry)["questions"] == before


@pytest.mark.parametrize("field,value", [("options", [{"label": "B", "markdown": "新选项"}]),
    ("subquestions", ["新子问"]), ("teachingNoteMarkdown", "新说明"), ("titleMarkdown", "新标题")])
def test_content_sections_participate_in_hash(field, value):
    a = load(); b = copy.deepcopy(a); b["questions"][0]["content"][field] = value
    assert result(a)["questions"][0]["contentHash"] != result(b)["questions"][0]["contentHash"]
