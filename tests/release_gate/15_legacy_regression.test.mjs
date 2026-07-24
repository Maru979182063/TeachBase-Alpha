import {
  expect,
  readJsonFixture,
} from "../helpers/runtime_testkit.mjs";
import { buildExportPayload, importApprovePublish } from "./release_gate_shared.mjs";

export function registerTests(register) {
  register({
    id: "RG-LEGACY-01",
    suite: "release_gate_legacy",
    title: "Legacy no-QVS runtime and export paths still work without triggering the new visual preflight contract",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("english", "minimal_bundle.json");
      const targetBundle = {
        ...bundle,
        bundle_id: `${bundle.bundle_id}_release_gate_legacy`,
        lesson_id: `${bundle.lesson_id}_release_gate_legacy`,
      };
      const server = await harness.startPostgresServer("release_gate_legacy_test");
      const health = await server.request("/health");
      expect(health.ok, "legacy_health_should_still_pass");
      const bootstrap = await server.request("/api/runtime/bootstrap", {
        method: "POST",
        body: {},
      });
      expect(bootstrap.ok, `legacy_bootstrap_failed:${JSON.stringify(bootstrap.data)}`);

      await importApprovePublish(server, targetBundle, "release_gate_legacy");
      const summary = await server.request("/api/runtime/summary");
      expect(summary.ok, `legacy_summary_failed:${JSON.stringify(summary.data)}`);

      const exportPayload = buildExportPayload({
        lessonId: targetBundle.lesson_id,
        title: targetBundle.title,
        stage: targetBundle.stage,
        grade: targetBundle.grade,
        season: targetBundle.season,
        questions: [
          {
            id: "legacy_export_question_1",
            localTaskId: targetBundle.tasks[0].local_task_id,
            localNumber: "1",
            checkpoint: targetBundle.tasks[0].checkpoint_codes?.[0] || "checkpoint",
            componentLabel: targetBundle.tasks[0].question_type,
            sourcePage: 1,
            previewText: targetBundle.tasks[0].stem,
            stem: targetBundle.tasks[0].stem,
            answer: targetBundle.tasks[0].answer,
            explanation: targetBundle.tasks[0].explanation,
          },
        ],
      });
      const exportRun = await server.request("/api/export/generate", {
        method: "POST",
        body: exportPayload,
      });
      expect(exportRun.ok, `legacy_export_failed:${JSON.stringify(exportRun.data)}`);
      expect(
        exportRun.data.item.preflight.checkedQuestionCount === 0,
        "legacy_export_should_skip_qvs_preflight"
      );
      return {
        lessonId: targetBundle.lesson_id,
        exportId: exportRun.data.item.id,
      };
    },
  });
}
