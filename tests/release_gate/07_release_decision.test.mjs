import { expect, readJsonFixture } from "../helpers/runtime_testkit.mjs";
import {
  buildReleaseDecisionOutputs,
} from "../../tools/build_release_decision.mjs";

function oneRecord(questionId, fields = {}) {
  return {
    question_id: questionId,
    ...fields,
  };
}

function decisionById(outputs, questionId) {
  return outputs.canonical_release_decision.decisions.find(
    (item) => item.question_id === questionId
  );
}

export function registerTests(register) {
  register({
    id: "RG-REL-01",
    suite: "release_gate_decision",
    title: "canonical_release_decision maps allow/review/block across transcription, asset, and split states",
    required: true,
    async run() {
      const outputs = buildReleaseDecisionOutputs({
        runId: "release_decision_rule_matrix",
        transcriptionResults: [
          oneRecord("case_allow", { quality_gate: "allow" }),
          oneRecord("case_transcription_block", { quality_gate: "block" }),
          oneRecord("case_asset_fail", { quality_gate: "allow" }),
          oneRecord("case_review", { quality_gate: "allow_with_review" }),
          oneRecord("case_no_split", { quality_gate: "allow" }),
        ],
        assetAuditResults: [
          oneRecord("case_allow", { status: "pass" }),
          oneRecord("case_transcription_block", { status: "pass" }),
          oneRecord("case_asset_fail", { status: "fail" }),
          oneRecord("case_review", { status: "needs_review" }),
          oneRecord("case_no_split", { status: "pass" }),
        ],
        splitAuditResults: [
          oneRecord("case_allow", { status: "AUDITED_READY" }),
          oneRecord("case_transcription_block", { status: "AUDITED_READY" }),
          oneRecord("case_asset_fail", { status: "AUDITED_READY" }),
          oneRecord("case_review", { status: "NEEDS_REVIEW" }),
        ],
      });

      expect(decisionById(outputs, "case_allow").decision === "allow", "case1_should_allow");
      expect(
        decisionById(outputs, "case_transcription_block").decision === "block",
        "case2_transcription_block_should_block"
      );
      expect(decisionById(outputs, "case_asset_fail").decision === "block", "case3_asset_fail_should_block");
      expect(decisionById(outputs, "case_review").decision === "review", "case4_review_should_review");
      expect(decisionById(outputs, "case_no_split").decision === "allow", "case5_absent_split_should_allow");
      expect(outputs.release_decision_summary.allow === 2, "summary_allow_count_mismatch");
      expect(outputs.release_decision_summary.review === 1, "summary_review_count_mismatch");
      expect(outputs.release_decision_summary.block === 2, "summary_block_count_mismatch");
      return outputs.release_decision_summary;
    },
  });

  register({
    id: "RG-REL-02",
    suite: "release_gate_decision",
    title: "Runtime import consumes allow_list_manifest and only imports allow questions",
    required: true,
    async run({ harness }) {
      const server = await harness.startFileServer({
        env: {
          RUNTIME_BACKBONE_STATE_DIR: harness.outputDir,
          RUNTIME_BACKBONE_STATE_PATH: `${harness.outputDir}/release_decision_runtime_state.json`,
        },
      });
      const bundle = await readJsonFixture("math", "minimal_bundle.json");
      const payload = {
        actor: "release_decision_test",
        requireReleaseDecision: true,
        bundle: {
          ...bundle,
          bundle_id: `${bundle.bundle_id}_release_decision`,
          lesson_id: `${bundle.lesson_id}_release_decision`,
        },
        allow_list_manifest: {
          schema_version: "allow_list_manifest.v0.1",
          run_id: "release_decision_import_filter",
          allow_question_ids: ["M-001"],
          review_question_ids: ["M-002"],
          block_question_ids: [],
        },
      };
      const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: payload,
      });
      expect(imported.ok, `release_decision_import_failed:${JSON.stringify(imported.data)}`);
      expect(imported.data.result.releaseGate.applied === true, "release_gate_not_applied");
      expect(imported.data.result.releaseGate.imported_task_count === 1, "allow_task_count_mismatch");
      expect(imported.data.result.releaseGate.review_task_count === 1, "review_task_count_mismatch");

      const state = await server.request("/api/runtime/debug/state");
      expect(state.ok, "debug_state_failed");
      const importedTasks = state.data.state.tasks.filter((item) =>
        item.lesson_id.endsWith("_release_decision")
      );
      expect(importedTasks.length === 1, `runtime_imported_non_allow_tasks:${importedTasks.length}`);
      expect(importedTasks[0].stable_question_no === "M-001", "wrong_task_imported");
      return {
        importedTaskIds: importedTasks.map((item) => item.stable_question_no),
        releaseGate: imported.data.result.releaseGate,
      };
    },
  });
}
