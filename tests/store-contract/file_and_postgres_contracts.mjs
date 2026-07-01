/**
 * 用途：
 * - 确认文件存储和 Postgres 存储在契约层表现一致。
 * - 存储语义变化时，先更新这个文件，再改后端特定测试。
 */

import {
  expect,
  expectEqual,
  readJsonFixture,
} from "../helpers/runtime_testkit.mjs";

function reorderBundle(bundle) {
  return {
    title: bundle.title,
    grade: bundle.grade,
    stage: bundle.stage,
    season: bundle.season,
    lesson_id: bundle.lesson_id,
    bundle_id: bundle.bundle_id,
    source_tree: bundle.source_tree.map((node) => ({
      title: node.title,
      phase: node.phase,
      node_type: node.node_type,
      source_node_local_id: node.source_node_local_id,
    })),
    subject: bundle.subject,
    tasks: bundle.tasks.map((task) => ({
      explanation: task.explanation,
      question_type: task.question_type,
      source_node_local_id: task.source_node_local_id,
      answer: task.answer,
      local_task_id: task.local_task_id,
      stem: task.stem,
      difficulty_confidence: task.difficulty_confidence,
      difficulty_source: task.difficulty_source,
      difficulty_scheme: task.difficulty_scheme,
      difficulty_level: task.difficulty_level,
      subject_tags: task.subject_tags,
      checkpoint_codes: task.checkpoint_codes,
      source_refs_json: task.source_refs_json,
    })),
  };
}

function buildVisualQuestionVisualStructure() {
  return {
    schema_version: "question_visual_structure.v1.1",
    generated_by: "contract_visual_manifest",
    runtime_run_id: "run_contract_visual_001",
    question_uid: "visual_doc_p003_q001",
    stem_md: "Choose the matching diagram.",
    answer_md: "A",
    analysis_md: "Option A matches the prompt.",
    legacy_stem_md:
      "Choose the matching diagram.\n\nA. ![qa_visual_doc_p003_q001_option_A_001](asset://qa_visual_doc_p003_q001_option_A_001)",
    gating: {
      mode: "auto",
      decision: "choice_detected",
    },
    options: [
      {
        option_key: "A",
        label_md: "A.",
        asset_ids: ["qa_visual_doc_p003_q001_option_A_001"],
      },
    ],
    content_blocks: [
      {
        block_type: "option_image",
        option_key: "A",
        asset_id: "qa_visual_doc_p003_q001_option_A_001",
      },
    ],
    visual_assets: [
      {
        asset_id: "qa_visual_doc_p003_q001_option_A_001",
        asset_role: "option",
        option_key: "A",
        placement_scope: "option_inline",
        display_ref: "asset://qa_visual_doc_p003_q001_option_A_001",
        storage_key:
          "question_assets/visual_doc_p003_q001/run_contract_visual_001/options/A/001.png",
        attach_status: "attached",
        file_status: "materialized",
        mime_type: "image/png",
        page_no: 3,
      },
    ],
    review_flags: [],
  };
}

function buildVisualManifestPayload(tag) {
  const qvs = buildVisualQuestionVisualStructure();
  return {
    actor: "contract_suite",
    bundle_id: `visual_contract_bundle_${tag}`,
    lesson_id: `visual_contract_lesson_${tag}`,
    title: "Visual Contract Validation Lesson",
    track_code: "english_senior",
    subject: "英语",
    stage: "senior",
    grade: "g11",
    season: "autumn",
    source_tree: [
      {
        source_node_local_id: "root",
        node_type: "lesson",
        phase: "reading_main",
        title: "Visual Contract Root",
        checkpoint_codes: ["阅读理解主旨大意"],
      },
    ],
    visualManifest: {
      schema_version: "question_asset_manifest.v0.1",
      generated_at: "2026-07-01T00:00:00.000Z",
      question_count: 1,
      asset_count: 1,
      questions: [
        {
          question_id: `visual_question_${tag}`,
          question_uid: qvs.question_uid,
          checkpoint: "阅读理解主旨大意",
          component_kind: "single_choice",
          stem_text_md: qvs.legacy_stem_md,
          answer_text_md: qvs.answer_md,
          analysis_text_md: qvs.analysis_md,
          question_visual_structure: qvs,
          merged_source_refs_json: {
            page_no: 3,
            bbox: {
              x: 24,
              y: 48,
              width: 260,
              height: 120,
            },
            audit_trace: {
              source: "visual_manifest_contract",
            },
            schema_versions: {
              question_visual_structure: "question_visual_structure.v1.1",
            },
            question_visual_structure: qvs,
          },
        },
      ],
    },
  };
}

function findLessonRevisionBundle(detail, lessonRevisionId) {
  return detail.lessonRevisions.find(
    (item) => item.lesson_revision_id === lessonRevisionId
  )?.bundle_jsonb;
}

async function importApprovePublish(server, bundle, actor = "contract_suite") {
  const reviewerActor = `${actor}_reviewer`;
  const publisherActor = `${actor}_publisher`;
  const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
    method: "POST",
    body: {
      actor,
      bundle,
    },
  });
  expect(imported.ok, `import_failed:${JSON.stringify(imported.data)}`);
  const approved = await server.request(
    `/api/runtime/review-tasks/${imported.data.result.reviewTaskId}/approve`,
    {
      method: "POST",
      body: {
        actor: reviewerActor,
      },
    }
  );
  expect(approved.ok, `approve_failed:${JSON.stringify(approved.data)}`);
  const detailAfterApprove = await server.request(`/api/runtime/lessons/${bundle.lesson_id}`);
  expect(detailAfterApprove.ok, "detail_after_approve_failed");
  const published = await server.request(`/api/runtime/lessons/${bundle.lesson_id}/publish`, {
    method: "POST",
    body: {
      actor: publisherActor,
      lessonRevisionId: imported.data.result.lessonRevisionId,
    },
  });
  expect(published.ok, `publish_failed:${JSON.stringify(published.data)}`);
  const search = await server.request(
    `/api/runtime/task-projections/search?subject=${encodeURIComponent(bundle.subject)}&publishedOnly=true`
  );
  expect(search.ok, "published_search_failed");
  return {
    imported: imported.data.result,
    approved: approved.data.result,
    detailAfterApprove: detailAfterApprove.data.detail,
    published: published.data.result,
    searchItems: search.data.items.filter((item) => item.lesson_id === bundle.lesson_id),
  };
}

async function runPatchFlow(server) {
  const lessons = await server.request("/api/runtime/lessons");
  expect(lessons.ok, "seed_lessons_request_failed");
  const lessonId = lessons.data.items[0]?.lesson_id;
  expect(lessonId, "seed_lesson_missing");
  const detail = await server.request(`/api/runtime/lessons/${lessonId}`);
  const componentId = detail.data.detail.componentRevisions[0]?.component_id;
  expect(componentId, "seed_component_missing");
  const rerun = await server.request(`/api/runtime/components/${componentId}/rerun`, {
    method: "POST",
    body: {
      actor: "contract_suite",
      proposedText: "合同测试局部重跑文本",
      note: "contract patch",
    },
  });
  expect(rerun.ok, `component_rerun_failed:${JSON.stringify(rerun.data)}`);
  const patchId = rerun.data.result.patch.component_patch_candidate_id;
  const accepted = await server.request(`/api/runtime/component-patches/${patchId}/accept`, {
    method: "POST",
    body: {
      actor: "contract_reviewer",
    },
  });
  expect(accepted.ok, `component_patch_accept_failed:${JSON.stringify(accepted.data)}`);
  const duplicateAccept = await server.request(
    `/api/runtime/component-patches/${patchId}/accept`,
    {
      method: "POST",
      body: {
        actor: "contract_reviewer",
      },
    }
  );
  return {
    patchId,
    firstStatus: accepted.status,
    secondStatus: duplicateAccept.status,
    secondError: duplicateAccept.data?.error,
  };
}

export function registerTests(register) {
  register({
    id: "C03-D09",
    suite: "store_contract",
    title: "Canonical bundle hash keeps property-order-only imports idempotent in file and postgres modes",
    required: true,
    async run({ harness }) {
      const baseBundle = await readJsonFixture("math", "minimal_bundle.json");
      const reorderedBundle = reorderBundle(baseBundle);
      const fileServer = await harness.startFileServer("contract_file_hash");
      const postgresServer = await harness.startPostgresServer("contract_hash_test");

      const fileFirst = await fileServer.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "contract_suite",
          bundle: baseBundle,
        },
      });
      const fileSecond = await fileServer.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "contract_suite",
          bundle: reorderedBundle,
        },
      });
      const pgFirst = await postgresServer.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "contract_suite",
          bundle: baseBundle,
        },
      });
      const pgSecond = await postgresServer.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "contract_suite",
          bundle: reorderedBundle,
        },
      });

      expect(fileFirst.ok && fileSecond.ok && pgFirst.ok && pgSecond.ok, "canonical_import_requests_failed");
      expect(fileSecond.data.result.idempotent === true, "file_reordered_import_not_idempotent");
      expect(pgSecond.data.result.idempotent === true, "postgres_reordered_import_not_idempotent");
      expectEqual(
        fileFirst.data.result.lessonRevisionId,
        fileSecond.data.result.lessonRevisionId,
        "file_revision_changed_for_property_order_only_import"
      );
      expectEqual(
        pgFirst.data.result.lessonRevisionId,
        pgSecond.data.result.lessonRevisionId,
        "postgres_revision_changed_for_property_order_only_import"
      );
      return {
        fileRevisionId: fileFirst.data.result.lessonRevisionId,
        postgresRevisionId: pgFirst.data.result.lessonRevisionId,
      };
    },
  });

  register({
    id: "C07-C10",
    suite: "store_contract",
    title: "Approve and publish semantics stay aligned between file and postgres modes",
    required: true,
    async run({ harness }) {
      const baseBundle = await readJsonFixture("english", "minimal_bundle.json");
      const fileServer = await harness.startFileServer("contract_file_publish");
      const postgresServer = await harness.startPostgresServer("contract_publish_test");
      const fileFlow = await importApprovePublish(fileServer, {
        ...baseBundle,
        bundle_id: `${baseBundle.bundle_id}_file`,
        lesson_id: `${baseBundle.lesson_id}_file`,
      });
      const postgresFlow = await importApprovePublish(postgresServer, {
        ...baseBundle,
        bundle_id: `${baseBundle.bundle_id}_pg`,
        lesson_id: `${baseBundle.lesson_id}_pg`,
      });

      expect(
        fileFlow.detailAfterApprove.lesson.published_revision_id === null,
        "file_approve_should_not_publish"
      );
      expect(
        postgresFlow.detailAfterApprove.lesson.published_revision_id === null,
        "postgres_approve_should_not_publish"
      );
      expect(
        fileFlow.published.lesson.published_revision_id === fileFlow.imported.lessonRevisionId,
        "file_publish_should_switch_pointer"
      );
      expect(
        postgresFlow.published.lesson.published_revision_id === postgresFlow.imported.lessonRevisionId,
        "postgres_publish_should_switch_pointer"
      );
      expectEqual(fileFlow.searchItems.length, 2, "file_published_projection_count_mismatch");
      expectEqual(postgresFlow.searchItems.length, 2, "postgres_published_projection_count_mismatch");
      return {
        filePublicationId: fileFlow.published.publication.publication_id,
        postgresPublicationId: postgresFlow.published.publication.publication_id,
      };
    },
  });

  register({
    id: "C18-I17",
    suite: "store_contract",
    title: "Component patch double-accept is rejected consistently",
    required: true,
    async run({ harness }) {
      const fileServer = await harness.startFileServer("contract_file_patch");
      const postgresServer = await harness.startPostgresServer("contract_patch_test");
      const fileResult = await runPatchFlow(fileServer);
      const pgResult = await runPatchFlow(postgresServer);
      expectEqual(fileResult.secondStatus, 409, "file_patch_second_accept_should_conflict");
      expectEqual(pgResult.secondStatus, 409, "postgres_patch_second_accept_should_conflict");
      expect(fileResult.secondError === "component_patch_not_pending", "file_patch_conflict_error_mismatch");
      expect(pgResult.secondError === "component_patch_not_pending", "postgres_patch_conflict_error_mismatch");
      return {
        filePatchId: fileResult.patchId,
        postgresPatchId: pgResult.patchId,
      };
    },
  });

  register({
    id: "C24-VIS",
    suite: "store_contract",
    title: "Visual manifest adapter keeps question_visual_structure alive through import and rerun in file and postgres modes",
    required: true,
    async run({ harness }) {
      const payload = buildVisualManifestPayload("adapter");
      const fileServer = await harness.startFileServer("contract_visual_file");
      const postgresServer = await harness.startPostgresServer("contract_visual_pg_test");

      const runFlow = async (server, tag) => {
        const requestPayload = {
          ...payload,
          bundle_id: `${payload.bundle_id}_${tag}`,
          lesson_id: `${payload.lesson_id}_${tag}`,
        };
        const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
          method: "POST",
          body: requestPayload,
        });
        expect(imported.ok, `visual_import_failed_${tag}:${JSON.stringify(imported.data)}`);

        const detail = await server.request(
          `/api/runtime/lessons/${requestPayload.lesson_id}`
        );
        expect(detail.ok, `visual_detail_failed_${tag}:${JSON.stringify(detail.data)}`);
        const importedBundle = findLessonRevisionBundle(
          detail.data.detail,
          imported.data.result.lessonRevisionId
        );
        const importedTask = importedBundle?.tasks?.[0];
        expect(importedTask, `visual_imported_task_missing_${tag}`);
        expect(
          importedTask.source_refs_json?.audit_trace?.source ===
            "visual_manifest_contract",
          `visual_audit_trace_missing_${tag}`
        );
        expect(
          importedTask.source_refs_json?.question_visual_structure?.runtime_run_id ===
            "run_contract_visual_001",
          `visual_runtime_run_id_missing_${tag}`
        );
        expect(
          importedTask.source_refs_json?.question_visual_structure?.visual_assets?.[0]
            ?.storage_key ===
            "question_assets/visual_doc_p003_q001/run_contract_visual_001/options/A/001.png",
          `visual_storage_key_missing_${tag}`
        );

        const projectionSearch = await server.request(
          `/api/runtime/task-projections/search?lessonId=${encodeURIComponent(requestPayload.lesson_id)}`
        );
        expect(
          projectionSearch.ok,
          `visual_projection_search_failed_${tag}:${JSON.stringify(projectionSearch.data)}`
        );
        const projection = projectionSearch.data.items.find(
          (item) => item.lesson_id === requestPayload.lesson_id
        );
        expect(projection, `visual_projection_missing_${tag}`);
        expect(
          projection.source_refs_json?.question_visual_structure?.question_uid ===
            "visual_doc_p003_q001",
          `visual_projection_qvs_missing_${tag}`
        );

        const rerun = await server.request(
          `/api/runtime/lessons/${requestPayload.lesson_id}/rerun`,
          {
            method: "POST",
            body: {
              actor: `contract_rerun_${tag}`,
            },
          }
        );
        expect(rerun.ok, `visual_rerun_failed_${tag}:${JSON.stringify(rerun.data)}`);

        const rerunDetail = await server.request(
          `/api/runtime/lessons/${requestPayload.lesson_id}`
        );
        expect(
          rerunDetail.ok,
          `visual_rerun_detail_failed_${tag}:${JSON.stringify(rerunDetail.data)}`
        );
        const rerunBundle = findLessonRevisionBundle(
          rerunDetail.data.detail,
          rerun.data.result.activeRevisionId
        );
        const rerunTask = rerunBundle?.tasks?.[0];
        expect(rerunTask, `visual_rerun_task_missing_${tag}`);
        expect(
          rerunTask.source_refs_json?.question_visual_structure?.question_uid ===
            "visual_doc_p003_q001",
          `visual_rerun_qvs_missing_${tag}`
        );
        expect(
          rerunTask.source_refs_json?.audit_trace?.source ===
            "visual_manifest_contract",
          `visual_rerun_audit_trace_missing_${tag}`
        );

        return {
          lessonId: requestPayload.lesson_id,
          lessonRevisionId: imported.data.result.lessonRevisionId,
          rerunRevisionId: rerun.data.result.activeRevisionId,
        };
      };

      const fileResult = await runFlow(fileServer, "file");
      const postgresResult = await runFlow(postgresServer, "pg");
      return {
        fileLessonId: fileResult.lessonId,
        postgresLessonId: postgresResult.lessonId,
        fileRerunRevisionId: fileResult.rerunRevisionId,
        postgresRerunRevisionId: postgresResult.rerunRevisionId,
      };
    },
  });
}
