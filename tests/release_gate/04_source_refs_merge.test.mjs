import {
  expect,
  runProcess,
} from "../helpers/runtime_testkit.mjs";
import {
  buildLegacySourceRefs,
  buildQuestionVisualStructure,
} from "./release_gate_shared.mjs";
import { mergeSourceRefsJson } from "../../tools/runtime_visual_split_adapter.mjs";
import { resolveBundledPythonPath } from "../../tools/runtime_dependency_paths.mjs";

export function registerTests(register) {
  register({
    id: "RG-SR-01",
    suite: "release_gate_source_refs",
    title: "source_refs_json merge preserves legacy keys while adding question_visual_structure.v1.1",
    required: true,
    async run() {
      const qvs = buildQuestionVisualStructure();
      const existing = {
        schema_versions: {
          legacy_source_refs: "v0.9",
        },
        legacy_source_refs: {
          document_id: "doc_001",
          page_no: 3,
          crop_artifact_id: "art_crop_old",
        },
        audit: {
          created_by: "old_runtime",
          old_run_id: "run_old",
        },
        manual_note: "人工确认过",
      };
      const merged = mergeSourceRefsJson(existing, qvs);
      expect(
        merged.legacy_source_refs?.document_id === "doc_001",
        "legacy_source_refs_lost"
      );
      expect(merged.audit?.old_run_id === "run_old", "audit_lost");
      expect(merged.manual_note === "人工确认过", "manual_note_lost");
      expect(
        merged.schema_versions?.legacy_source_refs === "v0.9",
        "legacy_schema_version_lost"
      );
      expect(
        merged.schema_versions?.question_visual_structure ===
          "question_visual_structure.v1.1",
        "qvs_schema_version_missing"
      );
      expect(
        merged.question_visual_structure?.question_uid === qvs.question_uid,
        "qvs_not_written"
      );
      expect(
        JSON.stringify(merged) !== JSON.stringify(qvs),
        "merged_payload_should_not_be_qvs_only"
      );
      return {
        questionUid: merged.question_visual_structure.question_uid,
      };
    },
  });

  register({
    id: "RG-SR-02",
    suite: "release_gate_source_refs",
    title: "Python merge helper keeps the old JSON and emits source_refs_merge_conflict on merge failure",
    required: true,
    async run() {
      const pythonExe = resolveBundledPythonPath() || process.env.PYTHON || "python";
      const script = `
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "tools"))
from source_refs_json_merge import merge_source_refs_json

class ExplodingQvs:
    def get(self, key, default=None):
        raise RuntimeError("boom")

existing = {
    "schema_versions": {"legacy_source_refs": "v0.9"},
    "legacy_source_refs": {"document_id": "doc_001"},
    "manual_note": "人工确认过",
}
merged, flags = merge_source_refs_json(existing, ExplodingQvs())
print(json.dumps({"merged": merged, "flags": flags}, ensure_ascii=False))
`;
      const result = await runProcess(pythonExe, ["-c", script]);
      expect(result.code === 0, `python_merge_helper_failed:${result.stderr || result.stdout}`);
      const parsed = JSON.parse(result.stdout.trim());
      expect(
        parsed.merged.legacy_source_refs.document_id === "doc_001",
        "python_merge_should_keep_existing_payload"
      );
      expect(
        parsed.flags.includes("source_refs_merge_conflict"),
        "python_merge_should_flag_conflict"
      );
      return parsed;
    },
  });

  register({
    id: "RG-SR-03",
    suite: "release_gate_source_refs",
    title: "Sequential re-read merge keeps concurrent additions alongside question_visual_structure",
    required: true,
    async run() {
      const qvs = buildQuestionVisualStructure();
      const existing = buildLegacySourceRefs(qvs);
      const writerB = {
        ...existing,
        key_b: "writer_b_value",
      };
      // Simulate the minimum safe write pattern: merge against the latest row,
      // not a stale in-memory snapshot.
      const finalState = mergeSourceRefsJson(writerB, qvs);
      expect(finalState.key_b === "writer_b_value", "concurrent_key_b_lost");
      expect(
        finalState.question_visual_structure?.question_uid === qvs.question_uid,
        "concurrent_qvs_lost"
      );
      return {
        keys: Object.keys(finalState).sort(),
      };
    },
  });
}
