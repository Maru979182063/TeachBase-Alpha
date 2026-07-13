import { expect, readJsonFixture } from "../helpers/runtime_testkit.mjs";
import {
  buildReleaseDecisionOutputs,
} from "../../tools/build_release_decision.mjs";
import {
  auditArtifactLineage,
} from "../../tools/audit_artifact_lineage.mjs";

function buildLineageFixture() {
  return buildReleaseDecisionOutputs({
    runId: "artifact_lineage_fixture",
    sourceRunId: "source_run_lineage_001",
    transcriptionResults: [
      {
        question_id: "M-001",
        quality_gate: "allow",
        lineage: {
          source_run_id: "source_run_lineage_001",
          source_document_id: "doc_math_001",
          document_revision_id: "doc_math_001_rev_001",
          semantic_node_id: "semantic_q_001",
        },
      },
    ],
    assetAuditResults: [
      {
        question_id: "M-001",
        status: "pass",
        assets: [
          {
            asset_id: "asset_math_001",
          },
        ],
      },
    ],
    splitAuditResults: [
      {
        question_id: "M-001",
        status: "AUDITED_READY",
      },
    ],
  });
}

function runtimeImportResultFor(outputs) {
  const lineage = outputs.allow_list_manifest.allow_items[0].lineage;
  return {
    result: {
      importId: "import_lineage_001",
      lineage: {
        schema_version: "runtime_import_lineage.v0.1",
        runtime_import_id: "import_lineage_001",
        items: [
          {
            ...lineage,
            runtime_import_id: "import_lineage_001",
          },
        ],
      },
    },
  };
}

export function registerTests(register) {
  register({
    id: "RG-LINEAGE-01",
    suite: "artifact_lineage",
    title: "Artifact lineage audit passes when release decision, assets, source run, and runtime trace are complete",
    required: true,
    async run() {
      const outputs = buildLineageFixture();
      const audit = auditArtifactLineage({
        canonicalReleaseDecision: outputs.canonical_release_decision,
        allowListManifest: outputs.allow_list_manifest,
        runtimeImportResult: runtimeImportResultFor(outputs),
      });
      expect(audit.total === 1, "lineage_total_mismatch");
      expect(audit.passed === 1, `lineage_should_pass:${JSON.stringify(audit.missing_fields)}`);
      expect(audit.failed === 0, "lineage_should_have_zero_failures");
      return audit;
    },
  });

  register({
    id: "RG-LINEAGE-02",
    suite: "artifact_lineage",
    title: "Artifact lineage audit fails when release_decision_id is missing",
    required: true,
    async run() {
      const outputs = buildLineageFixture();
      outputs.canonical_release_decision.decisions[0].release_decision_id = "";
      outputs.canonical_release_decision.decisions[0].lineage.release_decision_id = "";
      outputs.allow_list_manifest.allow_items[0].release_decision_id = "";
      outputs.allow_list_manifest.allow_items[0].lineage.release_decision_id = "";
      const runtimeResult = runtimeImportResultFor(outputs);
      runtimeResult.result.lineage.items[0].release_decision_id = "";
      const audit = auditArtifactLineage({
        canonicalReleaseDecision: outputs.canonical_release_decision,
        allowListManifest: outputs.allow_list_manifest,
        runtimeImportResult: runtimeResult,
      });
      expect(audit.failed === 1, "missing_release_decision_id_should_fail");
      expect(
        audit.missing_fields.some((item) => item.field === "release_decision_id"),
        "missing_release_decision_id_not_reported"
      );
      return audit;
    },
  });

  register({
    id: "RG-LINEAGE-03",
    suite: "artifact_lineage",
    title: "Artifact lineage audit fails when asset_ids are missing",
    required: true,
    async run() {
      const outputs = buildLineageFixture();
      outputs.canonical_release_decision.decisions[0].lineage.asset_ids = [];
      outputs.allow_list_manifest.allow_items[0].lineage.asset_ids = [];
      const runtimeResult = runtimeImportResultFor(outputs);
      runtimeResult.result.lineage.items[0].asset_ids = [];
      const audit = auditArtifactLineage({
        canonicalReleaseDecision: outputs.canonical_release_decision,
        allowListManifest: outputs.allow_list_manifest,
        runtimeImportResult: runtimeResult,
      });
      expect(audit.failed === 1, "missing_asset_id_should_fail");
      expect(audit.missing_fields.some((item) => item.field === "asset_ids"), "missing_asset_ids_not_reported");
      return audit;
    },
  });

  register({
    id: "RG-LINEAGE-04",
    suite: "artifact_lineage",
    title: "Runtime import response preserves release-gated lineage without changing the core model",
    required: true,
    async run({ harness }) {
      const server = await harness.startFileServer({
        env: {
          RUNTIME_BACKBONE_STATE_DIR: harness.outputDir,
          RUNTIME_BACKBONE_STATE_PATH: `${harness.outputDir}/artifact_lineage_runtime_state.json`,
        },
      });
      const bundle = await readJsonFixture("math", "minimal_bundle.json");
      const outputs = buildLineageFixture();
      const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "artifact_lineage_test",
          requireReleaseDecision: true,
          bundle: {
            ...bundle,
            bundle_id: `${bundle.bundle_id}_artifact_lineage`,
            lesson_id: `${bundle.lesson_id}_artifact_lineage`,
          },
          allow_list_manifest: outputs.allow_list_manifest,
        },
      });
      expect(imported.ok, `artifact_lineage_import_failed:${JSON.stringify(imported.data)}`);
      const lineageItems = imported.data.result.lineage.items;
      expect(lineageItems.length === 1, "runtime_lineage_item_count_mismatch");
      expect(lineageItems[0].question_id === "M-001", "runtime_lineage_question_id_mismatch");
      expect(lineageItems[0].runtime_import_id === imported.data.result.importId, "runtime_import_id_not_preserved");
      expect(lineageItems[0].asset_ids.includes("asset_math_001"), "runtime_lineage_asset_id_missing");

      const audit = auditArtifactLineage({
        canonicalReleaseDecision: outputs.canonical_release_decision,
        allowListManifest: outputs.allow_list_manifest,
        runtimeImportResult: imported.data,
      });
      expect(audit.failed === 0, `runtime_lineage_audit_failed:${JSON.stringify(audit.missing_fields)}`);
      return {
        importId: imported.data.result.importId,
        lineage: imported.data.result.lineage,
      };
    },
  });
}
