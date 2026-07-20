from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "english_knowledge_structure_projection_v01.py"
SPEC = importlib.util.spec_from_file_location("english_knowledge_structure_projection_v01", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
sys.modules["english_knowledge_structure_projection_v01"] = module
assert SPEC.loader
SPEC.loader.exec_module(module)


def test_repair_maps_open_relation_to_other() -> None:
    repaired = module.repair_model_payload(
        {
            "semantic_objects": [
                {
                    "object_id": "obj_1",
                    "source_bundle_refs": ["bundle_1"],
                    "open_description": "A knowledge module",
                    "primary_role": {"label": "knowledge_structure", "confidence": 0.9},
                    "source_evidence_refs": ["p1"],
                }
            ],
            "relations": [
                {
                    "subject_id": "obj_1",
                    "predicate": "learning_sequence_precedes",
                    "object_id": "obj_2",
                }
            ],
            "uncertainties": [],
        }
    )

    relation = repaired["payload"]["relations"][0]
    assert relation["subject"] == "obj_1"
    assert relation["object"] == "obj_2"
    assert relation["predicate"] == "other"
    assert relation["predicate_open_text"] == "learning_sequence_precedes"
    assert not module.validate_model_payload(repaired["payload"])


def test_projector_keeps_knowledge_out_of_qbank_ready() -> None:
    projection = module.projection_from_verified_object(
        {
            "primary_role": {"label": "knowledge_structure", "confidence": 0.96},
            "layout_dependency": {"required": True, "reason": "table layout carries meaning"},
            "structure": {"representation_status": "asset_only"},
            "projection_facts": {
                "qbank_as_is_supported": False,
                "qbank_derivable": True,
                "knowledge_structure_supported": True,
                "faithful_material_supported": True,
            },
            "unresolved_required_evidence": False,
        },
        source_complete=True,
    )

    assert projection["qbank"]["status"] == "DERIVABLE"
    assert projection["knowledge_structure"]["status"] == "READY_WITH_ASSET"
    assert projection["faithful_material"]["status"] == "READY_WITH_ASSET"


def test_unresolved_source_blocks_all_targets() -> None:
    projection = module.projection_from_verified_object(
        {
            "primary_role": {"label": "knowledge_structure", "confidence": 0.96},
            "projection_facts": {
                "qbank_as_is_supported": False,
                "qbank_derivable": False,
                "knowledge_structure_supported": True,
            },
            "unresolved_required_evidence": True,
        },
        source_complete=True,
    )

    assert projection["qbank"]["status"] == "BLOCKED"
    assert projection["knowledge_structure"]["status"] == "BLOCKED"
    assert projection["faithful_material"]["status"] == "BLOCKED"


def test_partial_structure_blocks_knowledge_but_preserves_faithful_fragment() -> None:
    projection = module.projection_from_verified_object(
        {
            "primary_role": {"label": "knowledge_structure", "confidence": 0.92},
            "structure": {"representation_status": "partial"},
            "projection_facts": {
                "qbank_as_is_supported": False,
                "qbank_derivable": False,
                "knowledge_structure_supported": True,
            },
            "unresolved_required_evidence": False,
        },
        source_complete=True,
    )

    assert projection["qbank"]["status"] == "BLOCKED"
    assert projection["knowledge_structure"]["status"] == "BLOCKED"
    assert projection["faithful_material"]["status"] == "READY_WITH_ASSET"
