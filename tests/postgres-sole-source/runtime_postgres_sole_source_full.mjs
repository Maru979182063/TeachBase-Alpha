/**
 * Purpose:
 * - prove the official Postgres business path works without relying on runtime_state_snapshot
 * - separate snapshot read/write resilience from the broader validation-baseline suites
 */

import fs from "node:fs/promises";
import path from "node:path";
import {
  expect,
  readJsonFixture,
  workspaceRoot,
} from "../helpers/runtime_testkit.mjs";

async function importApprovePublish(server, bundle, actor) {
  const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
    method: "POST",
    body: {
      actor,
      bundle,
    },
  });
  expect(imported.ok, `${actor}_import_failed:${JSON.stringify(imported.data)}`);

  const approved = await server.request(
    `/api/runtime/review-tasks/${imported.data.result.reviewTaskId}/approve`,
    {
      method: "POST",
      body: {
        actor: `${actor}_reviewer`,
      },
    }
  );
  expect(approved.ok, `${actor}_approve_failed:${JSON.stringify(approved.data)}`);

  const published = await server.request(`/api/runtime/lessons/${bundle.lesson_id}/publish`, {
    method: "POST",
    body: {
      actor: `${actor}_publisher`,
      lessonRevisionId: imported.data.result.lessonRevisionId,
    },
  });
  expect(published.ok, `${actor}_publish_failed:${JSON.stringify(published.data)}`);
  return {
    imported: imported.data.result,
    published: published.data.result,
  };
}

function buildExportPayload(bundle) {
  return {
    lesson: {
      lesson_id: bundle.lesson_id,
      lesson_title: bundle.title,
      stage: bundle.stage,
      grade: bundle.grade,
      season: bundle.season,
      lesson_no: 1,
      source_pdf_name: `${bundle.lesson_id}.pdf`,
      knowledge_point_count: bundle.source_tree.length,
      objectives: "Validation export objective",
    },
    splitLesson: {
      lesson_id: bundle.lesson_id,
      question_count: bundle.tasks.length,
      tree: [
        {
          module: bundle.title,
          items: bundle.source_tree.map((item) => item.title || item.source_node_local_id),
        },
      ],
      auditSummary: {
        reviewedCount: bundle.tasks.length,
        pendingCount: 0,
      },
      questions: bundle.tasks.map((task, index) => ({
        id: `${bundle.lesson_id}_question_${index + 1}`,
        localNumber: task.local_task_id,
        checkpoint: task.checkpoint_codes?.[0] || task.subject_tags?.[0] || "checkpoint",
        componentLabel: task.question_type,
        sourcePage: task.source_refs_json?.page_no || 1,
        effectiveVersionTags: ["基础版"],
        versionTags: ["基础版"],
        reviewNote: "validation export note",
        risk: "低风险",
      })),
    },
    reviewQueue: [],
    selectedVersions: ["基础版"],
    selectedAudiences: ["教师版"],
    selectedFormats: ["DOCX"],
    includeCompass: false,
  };
}

async function createRecoveredJob(harness, connectionString, lessonRevisionId) {
  await harness.queryDatabase(
    connectionString,
    `
      insert into run (
        run_id,
        run_type,
        root_target_type,
        root_target_id,
        subject,
        lane,
        status,
        triggered_by,
        started_at,
        finished_at
      )
      values (
        'snapshot_full_run',
        'validation',
        'lesson_revision',
        $1,
        '英语',
        'interactive',
        'running',
        'snapshot_suite',
        now() - interval '10 minutes',
        null
      )
    `,
    [lessonRevisionId]
  );
  await harness.queryDatabase(
    connectionString,
    `
      insert into job (
        job_id,
        run_id,
        job_type,
        lane,
        capability,
        resource_class,
        priority,
        idempotency_key,
        status,
        attempt_count,
        max_attempts,
        lease_expires_at,
        heartbeat_at,
        timeout_at,
        cancel_requested_at,
        next_retry_at,
        error_code,
        error_detail_ref,
        payload_ref,
        result_artifact_id,
        created_at,
        updated_at
      )
      values (
        'snapshot_full_job',
        'snapshot_full_run',
        'validation_job',
        'interactive',
        'export',
        'S',
        1,
        'snapshot_full_job_key',
        'running',
        1,
        3,
        null,
        now() - interval '10 minutes',
        now() - interval '1 minute',
        null,
        null,
        null,
        null,
        'payload.json',
        null,
        now() - interval '10 minutes',
        now() - interval '10 minutes'
      )
    `
  );
  await harness.queryDatabase(
    connectionString,
    `
      insert into job_attempt (
        job_attempt_id,
        job_id,
        attempt_no,
        started_at,
        heartbeat_at,
        finished_at,
        status,
        error_detail_json,
        worker_ref
      )
      values (
        'snapshot_full_attempt',
        'snapshot_full_job',
        1,
        now() - interval '10 minutes',
        now() - interval '10 minutes',
        null,
        'running',
        null,
        'snapshot_suite'
      )
    `
  );
}

async function upsertCorruptSnapshot(harness, connectionString) {
  await harness.queryDatabase(
    connectionString,
    `
      insert into runtime_state_snapshot (
        snapshot_key,
        snapshot_json,
        snapshot_version,
        snapshot_content_hash,
        updated_at
      )
      values (
        'default',
        '{"lessons":[{"lesson_id":"bogus_snapshot_lesson","title":"wrong"}],"questionBankItems":[{"question_bank_item_id":"bogus"}]}'::jsonb,
        909,
        'bogus_snapshot_hash',
        now()
      )
      on conflict (snapshot_key)
      do update
      set snapshot_json = excluded.snapshot_json,
          snapshot_version = excluded.snapshot_version,
          snapshot_content_hash = excluded.snapshot_content_hash,
          updated_at = excluded.updated_at
    `
  );
}

export function registerTests(register) {
  register({
    id: "PGSSF-01",
    suite: "postgres_sole_source_full",
    title: "A full business lifecycle succeeds with zero snapshot rows and still survives restart",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("english", "minimal_bundle.json");
      const lessonId = `${bundle.lesson_id}_full_a`;
      const database = await harness.createPostgresDatabase("pgss_full_a_test");
      const server = await harness.startPostgresServer({
        database,
        env: {
          POSTGRES_SOLE_SOURCE: "true",
        },
      });

      await harness.queryDatabase(
        database.connectionString,
        "delete from runtime_state_snapshot where snapshot_key = 'default'"
      );

      const published = await importApprovePublish(
        server,
        {
          ...bundle,
          lesson_id: lessonId,
          bundle_id: `${bundle.bundle_id}_full_a`,
        },
        "pgssf_a"
      );

      const projectionSearch = await server.request(
        `/api/runtime/task-projections/search?subject=${encodeURIComponent(bundle.subject)}&trackCode=english_senior&publishedOnly=true`
      );
      expect(projectionSearch.ok, "pgssf_a_projection_search_failed");
      expect(
        projectionSearch.data.items.filter((item) => item.lesson_id === lessonId).length === 2,
        "pgssf_a_projection_count_mismatch"
      );

      const createdItem = await server.request("/api/question-bank/items", {
        method: "POST",
        body: {
          actor: "pgssf_a_qb",
          taskProjectionId: projectionSearch.data.items.find((item) => item.lesson_id === lessonId)
            .task_projection_id,
        },
      });
      expect(createdItem.ok, `pgssf_a_qb_create_failed:${JSON.stringify(createdItem.data)}`);

      const questionBankSearch = await server.request(
        `/api/question-bank/search?subject=${encodeURIComponent(bundle.subject)}&trackCode=english_senior`
      );
      expect(questionBankSearch.ok, "pgssf_a_qb_search_failed");
      expect(
        questionBankSearch.data.items.some(
          (item) => item.question_bank_item_revision_id === createdItem.data.result.revision.question_bank_item_revision_id
        ),
        "pgssf_a_qb_revision_missing"
      );

      const build = await server.request("/api/material-builds", {
        method: "POST",
        body: {
          actor: "pgssf_a_material",
          lessonId,
          teacherName: "validation_teacher",
          buildName: "pgssf_a_build",
        },
      });
      expect(build.ok, `pgssf_a_material_build_failed:${JSON.stringify(build.data)}`);

      const addItems = await server.request(
        `/api/material-builds/${build.data.result.material_build_id}/items`,
        {
          method: "POST",
          body: {
            items: [
              {
                questionBankItemRevisionId: createdItem.data.result.revision.question_bank_item_revision_id,
                sectionKey: "body",
                sortIndex: 1,
              },
            ],
          },
        }
      );
      expect(addItems.ok, `pgssf_a_material_item_failed:${JSON.stringify(addItems.data)}`);

      const materialExport = await server.request(
        `/api/material-builds/${build.data.result.material_build_id}/export`,
        {
          method: "POST",
          body: {
            actor: "pgssf_a_exporter",
          },
        }
      );
      expect(materialExport.ok, `pgssf_a_material_export_failed:${JSON.stringify(materialExport.data)}`);

      const detail = await server.request(`/api/runtime/lessons/${lessonId}`);
      expect(detail.ok, `pgssf_a_detail_failed:${JSON.stringify(detail.data)}`);
      const componentId = detail.data.detail.componentRevisions[0]?.component_id;
      expect(componentId, "pgssf_a_component_missing");
      const rerun = await server.request(`/api/runtime/components/${componentId}/rerun`, {
        method: "POST",
        body: {
          actor: "pgssf_a_rerun",
          proposedText: "pgssf a rerun text",
          note: "pgssf a rerun note",
        },
      });
      expect(rerun.ok, `pgssf_a_rerun_failed:${JSON.stringify(rerun.data)}`);
      const accepted = await server.request(
        `/api/runtime/component-patches/${rerun.data.result.patch.component_patch_candidate_id}/accept`,
        {
          method: "POST",
          body: {
            actor: "pgssf_a_reviewer",
          },
        }
      );
      expect(accepted.ok, `pgssf_a_patch_accept_failed:${JSON.stringify(accepted.data)}`);

      await createRecoveredJob(
        harness,
        database.connectionString,
        published.published.lessonRevision.lesson_revision_id
      );
      const recovered = await server.request("/api/runtime/jobs/recover", {
        method: "POST",
        body: {
          actor: "pgssf_a_recovery",
        },
      });
      expect(recovered.ok, `pgssf_a_recover_failed:${JSON.stringify(recovered.data)}`);
      expect(recovered.data.items.some((item) => item.job_id === "snapshot_full_job"), "pgssf_a_job_not_recovered");

      const exportRun = await server.request("/api/export/generate", {
        method: "POST",
        body: buildExportPayload({
          ...bundle,
          lesson_id: lessonId,
        }),
      });
      expect(exportRun.ok, `pgssf_a_export_generate_failed:${JSON.stringify(exportRun.data)}`);
      const lineage = await server.request(
        `/api/runtime/artifacts/${exportRun.data.item.runtime.exportArtifactId}/lineage`
      );
      expect(lineage.ok, `pgssf_a_lineage_failed:${JSON.stringify(lineage.data)}`);
      expect(lineage.data.detail.nodes.length >= 1, "pgssf_a_lineage_should_have_nodes");

      await server.stop();
      const restarted = await harness.startPostgresServer({
        database,
        env: {
          POSTGRES_SOLE_SOURCE: "true",
        },
      });
      const restartedDetail = await restarted.request(`/api/runtime/lessons/${lessonId}`);
      expect(restartedDetail.ok, `pgssf_a_restart_detail_failed:${JSON.stringify(restartedDetail.data)}`);
      const restartedSearch = await restarted.request(
        `/api/runtime/task-projections/search?subject=${encodeURIComponent(bundle.subject)}&trackCode=english_senior&publishedOnly=true`
      );
      expect(restartedSearch.ok, `pgssf_a_restart_search_failed:${JSON.stringify(restartedSearch.data)}`);
      expect(
        restartedSearch.data.items.filter((item) => item.lesson_id === lessonId).length === 2,
        "pgssf_a_restart_projection_count_mismatch"
      );

      const snapshotCount = await harness.queryDatabase(
        database.connectionString,
        "select count(*)::int as count from runtime_state_snapshot"
      );
      expect(Number(snapshotCount.rows[0].count) === 0, "pgssf_a_snapshot_rows_should_remain_zero");
      return {
        lessonId,
        exportArtifactId: exportRun.data.item.runtime.exportArtifactId,
        snapshotCount: Number(snapshotCount.rows[0].count),
      };
    },
  });

  register({
    id: "PGSSF-02",
    suite: "postgres_sole_source_full",
    title: "Corrupt snapshot rows do not affect official reads or follow-up publishes after restart",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("english", "minimal_bundle.json");
      const lessonId = `${bundle.lesson_id}_full_b`;
      const database = await harness.createPostgresDatabase("pgss_full_b_test");
      const firstServer = await harness.startPostgresServer({
        database,
        env: {
          POSTGRES_SOLE_SOURCE: "true",
        },
      });

      await importApprovePublish(
        firstServer,
        {
          ...bundle,
          lesson_id: lessonId,
          bundle_id: `${bundle.bundle_id}_full_b`,
        },
        "pgssf_b"
      );
      await upsertCorruptSnapshot(harness, database.connectionString);
      await firstServer.stop();

      const restarted = await harness.startPostgresServer({
        database,
        env: {
          POSTGRES_SOLE_SOURCE: "true",
        },
      });

      const detail = await restarted.request(`/api/runtime/lessons/${lessonId}`);
      expect(detail.ok, `pgssf_b_detail_failed:${JSON.stringify(detail.data)}`);
      expect(detail.data.detail.lesson.lesson_id === lessonId, "pgssf_b_lesson_should_come_from_tables");

      const changedBundle = {
        ...bundle,
        lesson_id: lessonId,
        bundle_id: `${bundle.bundle_id}_full_b_2`,
        tasks: bundle.tasks.map((task, index) =>
          index === 0 ? { ...task, stem: `${task.stem} updated` } : task
        ),
      };
      const secondPublish = await importApprovePublish(restarted, changedBundle, "pgssf_b_second");
      const search = await restarted.request(
        `/api/runtime/task-projections/search?subject=${encodeURIComponent(bundle.subject)}&trackCode=english_senior&publishedOnly=true`
      );
      expect(search.ok, `pgssf_b_search_failed:${JSON.stringify(search.data)}`);
      expect(
        !search.data.items.some((item) => item.lesson_id === "bogus_snapshot_lesson"),
        "pgssf_b_snapshot_lesson_should_never_leak"
      );

      const snapshotRow = await harness.queryDatabase(
        database.connectionString,
        "select snapshot_version, snapshot_content_hash from runtime_state_snapshot where snapshot_key = 'default'"
      );
      expect(Number(snapshotRow.rows[0].snapshot_version) === 909, "pgssf_b_snapshot_version_should_remain_corrupt");
      return {
        lessonId,
        secondRevisionId: secondPublish.published.lessonRevision.lesson_revision_id,
        snapshotVersion: Number(snapshotRow.rows[0].snapshot_version),
      };
    },
  });

  register({
    id: "PGSSF-03",
    suite: "postgres_sole_source_full",
    title: "Snapshot write failures are recorded as warnings and do not roll back business writes",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("math", "minimal_bundle.json");
      const lessonId = `${bundle.lesson_id}_full_c`;
      const database = await harness.createPostgresDatabase("pgss_full_c_test");
      const server = await harness.startPostgresServer({
        database,
        env: {
          POSTGRES_SOLE_SOURCE: "true",
          RUNTIME_POSTGRES_EMIT_DEBUG_SNAPSHOT: "true",
        },
      });

      await harness.queryDatabase(database.connectionString, "drop table runtime_state_snapshot");
      const published = await importApprovePublish(
        server,
        {
          ...bundle,
          lesson_id: lessonId,
          bundle_id: `${bundle.bundle_id}_full_c`,
        },
        "pgssf_c"
      );

      const detail = await server.request(`/api/runtime/lessons/${lessonId}`);
      expect(detail.ok, `pgssf_c_detail_failed:${JSON.stringify(detail.data)}`);
      const health = await server.request("/health");
      expect(health.ok, "pgssf_c_health_failed");
      expect(
        health.data.storeHealth?.debugSnapshotMirror?.status === "failed",
        "pgssf_c_snapshot_failure_should_be_reported"
      );
      expect(
        detail.data.detail.lesson.published_revision_id ===
          published.published.lessonRevision.lesson_revision_id,
        "pgssf_c_business_write_should_not_roll_back"
      );
      return {
        lessonId,
        snapshotStatus: health.data.storeHealth.debugSnapshotMirror.status,
      };
    },
  });

  register({
    id: "PGSSF-04",
    suite: "postgres_sole_source_full",
    title: "Official business code paths only reference snapshot helpers through the explicit debug snapshot repository",
    required: true,
    async run() {
      const businessFiles = [
        path.join(workspaceRoot, "tools", "mock_workbench_api_server.mjs"),
        path.join(workspaceRoot, "tools", "runtime_backbone_store.mjs"),
        path.join(workspaceRoot, "tools", "runtime_backbone_store_interface.mjs"),
      ];
      for (const filePath of businessFiles) {
        const source = await fs.readFile(filePath, "utf8");
        expect(!source.includes("runtime_state_snapshot"), `snapshot_table_reference_not_allowed:${path.basename(filePath)}`);
        expect(!source.includes("snapshot_json"), `snapshot_json_reference_not_allowed:${path.basename(filePath)}`);
      }

      const postgresStoreSource = await fs.readFile(
        path.join(workspaceRoot, "tools", "runtime_backbone_postgres_store.mjs"),
        "utf8"
      );
      expect(
        postgresStoreSource.includes("writeSnapshotBestEffort") &&
          postgresStoreSource.includes("readSnapshotInfo"),
        "postgres_store_should_use_explicit_snapshot_repository"
      );
      expect(
        !postgresStoreSource.includes("select snapshot_json"),
        "postgres_store_should_not_query_snapshot_payload_directly"
      );
      return {
        auditedFiles: businessFiles.length + 1,
      };
    },
  });
}
