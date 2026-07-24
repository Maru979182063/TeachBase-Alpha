/**
 * 用途：
 * - 验证备份、恢复和行数恢复行为。
 * - 发布运行时改动前，用这个套件证明灾备流程可靠。
 */

import fs from "node:fs";
import path from "node:path";
import {
  expect,
  readJsonFixture,
  runProcess,
} from "../helpers/runtime_testkit.mjs";

function findPgTool(toolName) {
  const candidates = [];
  if (process.env.POSTGRES_BIN_DIR) {
    candidates.push(path.join(process.env.POSTGRES_BIN_DIR, `${toolName}.exe`));
  }
  for (const version of ["18", "17", "16", "15"]) {
    candidates.push(path.join("C:\\", "Program Files", "PostgreSQL", version, "bin", `${toolName}.exe`));
  }
  return candidates.find((candidate) => fs.existsSync(candidate)) || null;
}

async function tableCounts(harness, connectionString) {
  const result = await harness.queryDatabase(
    connectionString,
    `
      select
        (select count(*) from lesson) as lesson_count,
        (select count(*) from lesson_revision) as lesson_revision_count,
        (select count(*) from task_projection) as task_projection_count,
        (select count(*) from publication) as publication_count,
        (select count(*) from artifact) as artifact_count
    `
  );
  return result.rows[0];
}

export function registerTests(register) {
  register({
    id: "N01-N04",
    suite: "backup_restore",
    title: "pg_dump and pg_restore can recreate the runtime facts into a fresh database",
    required: true,
    async run({ harness }) {
      const pgDump = findPgTool("pg_dump");
      const pgRestore = findPgTool("pg_restore");
      expect(pgDump, "pg_dump_not_available");
      expect(pgRestore, "pg_restore_not_available");

      const bundle = await readJsonFixture("math", "minimal_bundle.json");
      const server = await harness.startPostgresServer("backup_restore_test");
      const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "backup_suite",
          bundle: {
            ...bundle,
            bundle_id: `${bundle.bundle_id}_backup`,
            lesson_id: `${bundle.lesson_id}_backup`,
          },
        },
      });
      expect(imported.ok, "backup_setup_import_failed");
      await server.request(`/api/runtime/review-tasks/${imported.data.result.reviewTaskId}/approve`, {
        method: "POST",
        body: {
          actor: "backup_reviewer",
        },
      });
      await server.request(`/api/runtime/lessons/${bundle.lesson_id}_backup/publish`, {
        method: "POST",
        body: {
          actor: "backup_publisher",
          lessonRevisionId: imported.data.result.lessonRevisionId,
        },
      });

      const backupFile = path.join(harness.outputDir, "runtime_backup.dump");
      const dumpResult = await runProcess(pgDump, [
        `--dbname=${server.database.connectionString}`,
        "--format=custom",
        `--file=${backupFile}`,
      ]);
      expect(dumpResult.code === 0, `pg_dump_failed:${dumpResult.stderr || dumpResult.stdout}`);

      const restoreDatabase = await harness.createPostgresDatabase("restore_test");
      const restoreResult = await runProcess(pgRestore, [
        `--dbname=${restoreDatabase.connectionString}`,
        "--clean",
        "--if-exists",
        "--no-owner",
        backupFile,
      ]);
      expect(
        restoreResult.code === 0,
        `pg_restore_failed:${restoreResult.stderr || restoreResult.stdout}`
      );

      const originalCounts = await tableCounts(harness, server.database.connectionString);
      const restoredCounts = await tableCounts(harness, restoreDatabase.connectionString);
      expect(
        JSON.stringify(originalCounts) === JSON.stringify(restoredCounts),
        `backup_restore_count_mismatch:${JSON.stringify({ originalCounts, restoredCounts })}`
      );
      return {
        backupFile,
        originalCounts,
        restoredCounts,
      };
    },
  });
}
