import fs from "node:fs/promises";
import path from "node:path";

import {
  expect,
  readJsonFixture,
  runProcess,
  workspaceRoot,
} from "../helpers/runtime_testkit.mjs";
import {
  resolveQuestionVisualAsset,
  validateQuestionVisualSourceRefs,
} from "../../tools/runtime_visual_split_adapter.mjs";
import {
  buildExportPayload,
  buildSeedSummary,
  buildVisualManifestImportPayload,
  ensureTinyPng,
  importApprovePublish,
  resolvePgTool,
  shortHash,
} from "./release_gate_shared.mjs";

async function executePgDump({
  connectionString,
  backupFile,
  localPgDump,
}) {
  if (localPgDump) {
    return runProcess(localPgDump, [
      `--dbname=${connectionString}`,
      "--format=custom",
      `--file=${backupFile}`,
    ]);
  }
  const parsed = new URL(connectionString);
  const dockerImage = process.env.RELEASE_GATE_PG_TOOLS_IMAGE || "postgres:18";
  return runProcess("docker", [
    "run",
    "--rm",
    "--add-host",
    "host.docker.internal:host-gateway",
    "-e",
    `PGPASSWORD=${decodeURIComponent(parsed.password || "")}`,
    "-v",
    `${path.dirname(backupFile)}:/backup`,
    dockerImage,
    "pg_dump",
    "--host",
    "host.docker.internal",
    "--port",
    parsed.port || "5432",
    "--username",
    decodeURIComponent(parsed.username || "postgres"),
    "--dbname",
    parsed.pathname.replace(/^\//, ""),
    "--format=custom",
    "--file",
    `/backup/${path.basename(backupFile)}`,
  ]);
}

async function executePgRestore({
  connectionString,
  backupFile,
  localPgRestore,
}) {
  if (localPgRestore) {
    return runProcess(localPgRestore, [
      `--dbname=${connectionString}`,
      "--clean",
      "--if-exists",
      "--no-owner",
      backupFile,
    ]);
  }
  const parsed = new URL(connectionString);
  const dockerImage = process.env.RELEASE_GATE_PG_TOOLS_IMAGE || "postgres:18";
  return runProcess("docker", [
    "run",
    "--rm",
    "--add-host",
    "host.docker.internal:host-gateway",
    "-e",
    `PGPASSWORD=${decodeURIComponent(parsed.password || "")}`,
    "-v",
    `${path.dirname(backupFile)}:/backup`,
    dockerImage,
    "pg_restore",
    "--host",
    "host.docker.internal",
    "--port",
    parsed.port || "5432",
    "--username",
    decodeURIComponent(parsed.username || "postgres"),
    "--dbname",
    parsed.pathname.replace(/^\//, ""),
    "--clean",
    "--if-exists",
    "--no-owner",
    `/backup/${path.basename(backupFile)}`,
  ]);
}

export function registerTests(register) {
  register({
    id: "RG-BACKUP-01",
    suite: "release_gate_backup_restore",
    title: "Backup and restore preserve runtime facts, QVS payloads, and post-restore exportability",
    required: true,
    async run({ harness, outputDir }) {
      const [localPgDump, localPgRestore, gitCommit] = await Promise.all([
        resolvePgTool("pg_dump"),
        resolvePgTool("pg_restore"),
        runProcess("git", ["rev-parse", "--short", "HEAD"]),
      ]);
      expect(
        localPgDump || localPgRestore ? Boolean(localPgDump && localPgRestore) : true,
        "pg_dump_pg_restore_must_be_paired_when_using_local_tools"
      );

      const payload = buildVisualManifestImportPayload("backup_restore");
      const qvs =
        payload.visualManifest.questions[0].question_visual_structure;
      const assetBaseDir = path.join(outputDir, "visual_asset_bundle");
      await ensureTinyPng(assetBaseDir, qvs.visual_assets[0].storage_key);

      const server = await harness.startPostgresServer("release_gate_backup_restore_test");
      const primaryBundle = await readJsonFixture("english", "minimal_bundle.json");
      const primaryLesson = {
        ...primaryBundle,
        bundle_id: `${primaryBundle.bundle_id}_backup_restore`,
        lesson_id: `${primaryBundle.lesson_id}_backup_restore`,
      };
      await importApprovePublish(
        server,
        primaryLesson,
        "release_gate_backup_primary"
      );
      const published = await importApprovePublish(
        server,
        payload,
        "release_gate_backup"
      );
      const projectionRows = await harness.queryDatabase(
        server.database.connectionString,
        `
          select task_projection_id
          from task_projection
          where lesson_id = $1
          order by created_at asc
          limit 1
        `,
        [primaryLesson.lesson_id]
      );
      const targetProjection = projectionRows.rows[0];
      expect(targetProjection, "backup_projection_missing");
      const createdItem = await server.request("/api/question-bank/items", {
        method: "POST",
        body: {
          actor: "release_gate_backup_qb",
          taskProjectionId: targetProjection.task_projection_id,
        },
      });
      expect(createdItem.ok, `backup_question_bank_create_failed:${JSON.stringify(createdItem.data)}`);

      const build = await server.request("/api/material-builds", {
        method: "POST",
        body: {
          actor: "release_gate_backup_material",
          lessonId: primaryLesson.lesson_id,
          teacherName: "release_gate_teacher",
          buildName: "release_gate_backup_build",
        },
      });
      expect(build.ok, `backup_material_build_failed:${JSON.stringify(build.data)}`);

      const addItems = await server.request(
        `/api/material-builds/${build.data.result.material_build_id}/items`,
        {
          method: "POST",
          body: {
            items: [
              {
                questionBankItemRevisionId:
                  createdItem.data.result.revision.question_bank_item_revision_id,
                sectionKey: "body",
                sortIndex: 1,
                includeAnswer: true,
                includeExplanation: true,
              },
            ],
          },
        }
      );
      expect(addItems.ok, `backup_material_item_failed:${JSON.stringify(addItems.data)}`);

      const materialExport = await server.request(
        `/api/material-builds/${build.data.result.material_build_id}/export`,
        {
          method: "POST",
          body: {
            actor: "release_gate_backup_material_exporter",
          },
        }
      );
      expect(materialExport.ok, `backup_material_export_failed:${JSON.stringify(materialExport.data)}`);

      const exportPayload = buildExportPayload({
        lessonId: payload.lesson_id,
        title: payload.title,
        stage: payload.stage,
        grade: payload.grade,
        season: payload.season,
        assetBaseDir,
        questions: [
          {
            id: "release_gate_backup_export_question",
            localTaskId: payload.visualManifest.questions[0].local_task_id,
            localNumber: "1",
            checkpoint: "阅读理解主旨大意",
            componentLabel: "single_choice",
            sourcePage: 3,
            question_visual_structure: qvs,
          },
        ],
      });
      const exportRun = await server.request("/api/export/generate", {
        method: "POST",
        body: exportPayload,
      });
      expect(exportRun.ok, `backup_export_generate_failed:${JSON.stringify(exportRun.data)}`);

      const beforeCounts = await buildSeedSummary(
        harness,
        server.database.connectionString
      );
      const backupDir = path.join(outputDir, "backups");
      await fs.mkdir(backupDir, { recursive: true });
      const backupFile = path.join(
        backupDir,
        `${new Date().toISOString().replace(/[:.]/g, "-")}_${(gitCommit.stdout || "nogit").trim() || "nogit"}_${shortHash(beforeCounts)}.dump`
      );

      const dump = await executePgDump({
        connectionString: server.database.connectionString,
        backupFile,
        localPgDump,
      });
      expect(dump.code === 0, `pg_dump_failed:${dump.stderr || dump.stdout}`);

      const restoreDatabase = await harness.createPostgresDatabase(
        "release_gate_restore_test"
      );
      const restore = await executePgRestore({
        connectionString: restoreDatabase.connectionString,
        backupFile,
        localPgRestore,
      });
      expect(restore.code === 0, `pg_restore_failed:${restore.stderr || restore.stdout}`);

      const afterCounts = await buildSeedSummary(
        harness,
        restoreDatabase.connectionString
      );
      expect(
        JSON.stringify(beforeCounts) === JSON.stringify(afterCounts),
        `backup_restore_count_mismatch:${JSON.stringify({ beforeCounts, afterCounts })}`
      );

      const restoredBundle = await harness.queryDatabase(
        restoreDatabase.connectionString,
        `
          select bundle_jsonb
          from lesson_revision
          where lesson_id = $1
          order by revision_no desc
          limit 1
        `,
        [payload.lesson_id]
      );
      expect(restoredBundle.rows.length === 1, "restored_visual_bundle_missing");
      const restoredTask =
        restoredBundle.rows[0]?.bundle_jsonb?.tasks?.[0] || null;
      const restoredSourceRefs =
        restoredTask?.source_refs_json ||
        restoredTask?.merged_source_refs_json ||
        (restoredTask?.question_visual_structure
          ? {
              question_visual_structure: restoredTask.question_visual_structure,
            }
          : null);
      expect(restoredSourceRefs, "restored_visual_source_refs_missing");
      const validation = validateQuestionVisualSourceRefs(
        restoredSourceRefs
      );
      expect(validation.ok, `restored_qvs_invalid:${JSON.stringify(validation)}`);
      const resolved = resolveQuestionVisualAsset(
        restoredSourceRefs,
        qvs.visual_assets[0].display_ref
      );
      expect(
        resolved.ok,
        `restored_asset_ref_unresolvable:${JSON.stringify(resolved)}`
      );

      const restoredServer = await harness.startPostgresServer({
        database: restoreDatabase,
        env: {
          POSTGRES_SOLE_SOURCE: "true",
        },
      });
      const health = await restoredServer.request("/health");
      expect(health.ok, "restored_health_failed");
      const detail = await restoredServer.request(
        `/api/runtime/lessons/${payload.lesson_id}`
      );
      expect(detail.ok, `restored_detail_failed:${JSON.stringify(detail.data)}`);
      const restoredExport = await restoredServer.request("/api/export/generate", {
        method: "POST",
        body: exportPayload,
      });
      expect(
        restoredExport.ok,
        `restored_export_failed:${JSON.stringify(restoredExport.data)}`
      );

      return {
        backupFile: path.relative(workspaceRoot, backupFile),
        beforeCounts,
        afterCounts,
        localTools: Boolean(localPgDump && localPgRestore),
      };
    },
  });
}
