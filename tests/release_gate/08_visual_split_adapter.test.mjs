import {
  expect,
} from "../helpers/runtime_testkit.mjs";
import {
  adaptQuestionAssetManifestToLessonDraftBundle,
  looksLikeVisualQuestionManifest,
  validateQuestionVisualSourceRefs,
} from "../../tools/runtime_visual_split_adapter.mjs";
import {
  buildQuestionVisualStructure,
} from "./release_gate_shared.mjs";

export function registerTests(register) {
  register({
    id: "RG-ADAPTER-01",
    suite: "release_gate_visual_adapter",
    title: "Visual split manifests adapt into LessonDraftBundle tasks without leaking crop paths into persisted source refs",
    required: true,
    async run() {
      const qvs = buildQuestionVisualStructure({
        question_uid: "adapter_fixture_q001",
        runtime_run_id: "run_adapter_fixture",
      });
      const manifest = {
        schema_version: "question_asset_manifest.v0.1",
        questions: [
          {
            question_id: "adapter_question_001",
            question_uid: "adapter_fixture_q001",
            local_task_id: "ADAPTER-001",
            checkpoint: "阅读理解主旨大意",
            component_kind: "single_choice",
            stem_text_md: qvs.legacy_stem_md,
            answer_text_md: qvs.answer_md,
            analysis_text_md: qvs.analysis_md,
            question_visual_structure: qvs,
            merged_source_refs_json: {
              page_no: 3,
              bbox: {
                x: 10,
                y: 20,
                width: 300,
                height: 120,
              },
              crop_path: "C:/tmp/debug-only/crop.png",
              audit_trace: {
                source: "visual_adapter_test",
              },
              question_visual_structure: qvs,
            },
          },
        ],
      };

      expect(looksLikeVisualQuestionManifest(manifest), "visual_manifest_shape_not_detected");
      const bundle = adaptQuestionAssetManifestToLessonDraftBundle(manifest, {
        bundle_id: "adapter_bundle",
        lesson_id: "adapter_lesson",
        title: "Adapter Lesson",
        subject: "英语",
        stage: "senior",
        track_code: "english_senior",
        source_tree: [
          {
            source_node_local_id: "root",
            node_type: "lesson",
            title: "Adapter Root",
          },
        ],
      });

      expect(bundle.tasks.length === 1, "adapter_task_count_mismatch");
      const task = bundle.tasks[0];
      expect(task.local_task_id === "ADAPTER-001", "adapter_local_task_id_mismatch");
      expect(task.question_type === "single_choice", "adapter_component_kind_mismatch");
      expect(task.source_refs_json.page_no === 3, "adapter_page_no_missing");
      expect(!("crop_path" in task.source_refs_json), "adapter_crop_path_should_not_persist");
      expect(
        task.source_refs_json.question_visual_structure?.runtime_run_id ===
          "run_adapter_fixture",
        "adapter_runtime_run_id_missing"
      );
      const validation = validateQuestionVisualSourceRefs(task.source_refs_json);
      expect(validation.ok, `adapter_normalized_source_refs_invalid:${JSON.stringify(validation)}`);
      return {
        localTaskId: task.local_task_id,
        questionUid: task.source_refs_json.question_visual_structure.question_uid,
      };
    },
  });
}
