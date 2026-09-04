"""将完整数学 DOCX 题包保存为 Java 待审核候选；只做结构映射，不做语义判断。"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
from pathlib import Path

import jsonschema
import requests

ROOT = Path(__file__).resolve().parents[1]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def final_packet_schema() -> dict:
    """模型合同之外，显式声明编排器已有的覆盖状态与结构化处理留证。"""
    schema = json.loads((ROOT / "schemas/docx_math_refined_question_packet.schema.json").read_text(encoding="utf-8"))
    schema["properties"].update({"source_field_coverage": {"type": "object"},
                                 "projection_coverage": {"type": "object"}})
    schema["properties"]["normalization_actions"]["items"] = {"oneOf": [
        {"type": "string"},
        {"type": "object", "anyOf": [{"required": ["action"]}, {"required": ["code"]}],
         "properties": {"action": {"type": "string", "minLength": 1},
                        "code": {"type": "string", "minLength": 1}}},
    ]}
    schema["properties"]["status_breakdown"]["properties"]["projection_status"]["enum"].append(
        "READY_WITH_COVERAGE_WARNINGS")
    return schema


def store_file(source: Path, storage: Path) -> dict:
    """按字节哈希保存不可变文件；已有同键文件必须逐字节一致。"""
    data = source.read_bytes()
    sha = digest(data)
    suffix = source.suffix.lower()
    key = f"sha256/{sha[:2]}/{sha}{suffix}"
    target = storage / key
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as output:
            output.write(data)
    except FileExistsError:
        if target.read_bytes() != data:
            raise ValueError(f"storage_hash_conflict:{sha}")
    return {"originalFilename": source.name, "storageProvider": "local", "storageKey": key,
            "mediaType": mimetypes.guess_type(source.name)[0] or "application/octet-stream",
            "sizeBytes": len(data), "sha256": sha}


def map_packet(packet: dict, source_sha: str, bundle_sha: str, subject: str,
               assets: dict, bundle_file: dict) -> dict:
    """正文与运行证据分开，逐字保留公式；不能将模型 READY 映射为人工批准。"""
    q = packet["standard_question"]
    if not q["stem_md"].strip():
        raise ValueError(f"candidate_stem_missing:{packet['source_group_id']}")
    if packet["refine_status"] not in {"REFINED_READY", "REFINED_NEEDS_REVIEW"}:
        raise ValueError(f"candidate_refinement_failed:{packet['source_group_id']}")
    # 无可靠跨轮题目身份时，限定在不可变题包中，避免边界重切后同序号误覆盖旧题。
    key = f"{source_sha}/{bundle_sha}/{packet['source_group_id']}"
    return {
        "externalKey": f"docx-math-{bundle_sha}-{packet['source_group_id']}",
        "sourceSystem": "doc_math", "sourceKey": key, "reviewStatus": "pending_review",
        "subject": subject, "stage": "", "grade": "", "questionType": packet["question_type"],
        "title": q["title"], "lesson": "", "primaryKnowledgeTag": "", "secondaryKnowledgeTags": [],
        "difficultyStars": None, "materialMarkdown": q["context_md"], "stemMarkdown": q["stem_md"],
        "options": q["options"], "answerMarkdown": q["answer_md"], "analysisMarkdown": q["explanation_md"],
        "content": q,
        "provenance": {"adapter": "docx_math_candidate_v1", "sourceSha256": source_sha,
                       "bundleSha256": bundle_sha, "bundleFile": bundle_file,
                       "upstreamPacket": packet, "assetFiles": assets,
                       "reviewPolicy": "human_review_required; render_compatibility_not_certified"},
        "sourcePayloadHash": digest(json_bytes(packet)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--asset-map", type=Path, required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--actor-user-id", required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    args = parser.parse_args()
    raw = args.packets.read_bytes()
    packets = json.loads(raw)["packets"]
    if not 1 <= len(packets) <= 100:
        raise ValueError("candidate_batch_size_out_of_range")
    schema = final_packet_schema()
    ids = set()
    for packet in packets:
        jsonschema.validate(packet, schema)
        if packet["source_group_id"] in ids:
            raise ValueError("candidate_group_id_duplicate")
        ids.add(packet["source_group_id"])
    source = store_file(args.source, args.storage_root)
    bundle = store_file(args.packets, args.storage_root)
    asset_map = json.loads(args.asset_map.read_text(encoding="utf-8"))
    assets = {}
    for item in asset_map["items"]:
        path = (ROOT / item["storage_key"]).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError("asset_path_outside_repository")
        file = store_file(path, args.storage_root)
        previous = assets.setdefault(item["asset_id"], file)
        if previous != file:
            raise ValueError("asset_id_content_conflict")
    evidence = [store_file(p, args.storage_root) for p in [args.asset_map, *args.evidence]]
    mapped = [map_packet(p, source["sha256"], digest(raw), args.subject, assets, bundle) for p in packets]
    # 对 asset:// 协议作结构检查，不依据正文词语决定图片归属。
    for item in mapped:
        for fragment in json.dumps(item["content"], ensure_ascii=False).split("asset://")[1:]:
            asset_id = fragment.split(")", 1)[0]
            if asset_id not in assets:
                raise ValueError(f"asset_reference_unresolved:{asset_id}")

    session = requests.Session()
    session.trust_env = False

    def post(endpoint: str, body: dict) -> dict:
        response = session.post(args.base_url.rstrip("/") + endpoint, json=body, timeout=120)
        if not response.ok:
            raise RuntimeError(f"http_{response.status_code}:{endpoint}:{response.text[:500]}")
        return response.json()

    registrations = {}
    for file in [source, bundle, *assets.values(), *evidence]:
        if file["sha256"] not in registrations:
            registrations[file["sha256"]] = post("/api/v1/files", {
                "workspaceId": args.workspace_id, "actorUserId": args.actor_user_id, **file})
    request = {
        "workspaceId": args.workspace_id, "actorUserId": args.actor_user_id,
        "sourceFileVersionId": registrations[source["sha256"]]["fileVersionId"],
        "sourceSha256": source["sha256"], "sourceType": "docx", "subject": args.subject,
        "title": args.source.stem,
        "sourceMetadata": {"adapter": "docx_math_candidate_v1", "sourceSha256": source["sha256"]},
        "questions": mapped,
    }
    save_json(args.out_dir / "candidate_request.json", request)
    save_json(args.out_dir / "file_registrations.json", registrations)
    result = post("/api/v1/ingestion/candidate-batches", request)
    save_json(args.out_dir / "candidate_receipt.json", result)
    print(json.dumps({"stored": len(result["results"]), "sourceDocumentId": result["sourceDocumentId"],
                      "registeredFiles": len(registrations), "status": "pending_review"}))


if __name__ == "__main__":
    main()
