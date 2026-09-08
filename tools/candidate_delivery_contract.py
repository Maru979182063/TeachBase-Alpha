"""G0 纯合同参考实现：无 HTTP、数据库、文件上传或加工节点调用。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/backend_candidate_delivery_v1.schema.json"
REGISTRY = ROOT / "docs/backend/contracts/identity-authorities.v1.json"


class ContractError(ValueError):
    pass


def canonical_bytes(value):
    """tb-json-v1：码点排序、无空白 UTF-8、整数；不 trim、不归一化 Unicode/LaTeX。"""
    def check(node):
        if node is None or isinstance(node, bool):
            return
        if isinstance(node, str):
            node.encode("utf-8", errors="strict")
        elif isinstance(node, int):
            if abs(node) > 9007199254740991:
                raise ContractError("unsafe_integer")
        elif isinstance(node, list):
            for child in node:
                check(child)
        elif isinstance(node, dict):
            for key, child in node.items():
                if not isinstance(key, str):
                    raise ContractError("non_string_key")
                check(key)
                check(child)
        else:
            raise ContractError("unsupported_json_number_or_type")
    check(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def content_hash(question):
    # 新合同专属内容摘要，不映射或覆盖旧 QuestionService 的历史哈希。
    return digest({"hashContract": "tb-content-v1", "content": question["content"]})


def request_digest(manifest):
    # 请求 ID 是重试键，不属于包内容；其余字段（包括来源及建议）均绑定本次交付。
    return digest({"hashContract": "tb-delivery-v1", "manifest": {
        key: value for key, value in manifest.items() if key != "importRequestId"}})


def identity_key(manifest, question, registry):
    identity = question["identity"]
    scope = (manifest["workspaceId"], manifest["sourceSystem"])
    if identity["mode"] == "one_shot_candidate":
        return (*scope, "one_shot_candidate", manifest["packageId"], identity["candidateId"])
    authority = next((r for r in registry["contracts"] if
        (r["sourceSystem"], r["identityContractId"], r["identityContractVersion"]) ==
        (manifest["sourceSystem"], identity["identityContractId"], identity["identityContractVersion"])), None)
    if authority is None:
        raise ContractError("stable_identity_contract_not_registered")
    if set(identity["anchorEvidence"]) != set(authority["anchorFields"]):
        raise ContractError("stable_anchor_fields_mismatch")
    document = next(d for d in manifest["sourceDocuments"] if d["documentKey"] == question["sourceDocumentKey"])
    if authority["requiresDocumentStableKey"] and document["documentStableKey"] is None:
        raise ContractError("document_stable_key_required")
    # opaque key 由来源分配；只按已登记命名空间拼接作用域，不从 evidence 或正文生成 key。
    return (*scope, "registered_stable", authority["stableKeyNamespace"], identity["stableQuestionKey"])


def validate_manifest(manifest, registry=None):
    if registry is None:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")), format_checker=FormatChecker())
    errors = list(validator.iter_errors(manifest))
    if errors:
        first = errors[0]
        raise ContractError("schema_invalid:" + "/".join(map(str, first.absolute_path)) + ":" + first.validator)
    canonical_bytes(manifest)

    def indexed(items, field):
        result = {item[field]: item for item in items}
        if len(result) != len(items):
            raise ContractError("duplicate_" + field)
        return result
    files = indexed(manifest["files"], "fileKey")
    documents = indexed(manifest["sourceDocuments"], "documentKey")
    indexed(manifest["questions"], "itemKey")
    for file in files.values():
        # 仅验证路径合同；本工具不读取包内实际文件，也不宣称字节校验已通过。
        path = file["path"]
        if any(c in path for c in ("\\", ":", "\0")) or any(p in ("", ".", "..") for p in path.split("/")):
            raise ContractError("package_path_invalid")
    for document in documents.values():
        if document["fileKey"] not in files:
            raise ContractError("source_file_unresolved")
    seen = set()
    results = []
    for question in manifest["questions"]:
        if question["sourceDocumentKey"] not in documents:
            raise ContractError("source_document_unresolved")
        for key in question["sourceEvidence"]["evidenceFileKeys"]:
            if key not in files:
                raise ContractError("evidence_file_unresolved")
        indexed(question["content"]["media"], "assetKey")
        available = {(f["sha256"], f["mediaType"]) for f in files.values()}
        for media in question["content"]["media"]:
            if (media["sha256"], media["mediaType"]) not in available:
                raise ContractError("media_manifest_unresolved")
        key = identity_key(manifest, question, registry)
        if key in seen:
            raise ContractError("duplicate_question_identity")
        seen.add(key)
        computed = content_hash(question)
        if question["contentHash"] is not None and question["contentHash"] != computed:
            raise ContractError("content_hash_mismatch")
        results.append({"itemKey": question["itemKey"], "identityMode": question["identity"]["mode"],
                        "identityKey": list(key), "contentHash": computed})
    return {"scope": "G0_contract_only", "requestDigest": request_digest(manifest), "questions": results,
            "databaseWritten": False, "assetBytesVerified": False, "durableReceiptImplemented": False}


def load_manifest(path):
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ContractError("duplicate_json_member")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_manifest(load_manifest(args.manifest)), ensure_ascii=False, indent=2))
