/**
 * Purpose:
 * - reproduce the current committed backend baseline from a clean local clone
 * - prove the result does not depend on the current dirty worktree or local untracked files
 */

import fs from "node:fs/promises";
import path from "node:path";
import {
  ensureDir,
  makeRunId,
  runProcess,
  workspaceRoot,
} from "../tests/helpers/runtime_testkit.mjs";

const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const tempRoot = path.win32.join("C:\\", "tmp", "jiaoyan-runtime-tests");
const hardcodedPathPatterns = ["C:/Users/EDY", "C:\\Users\\EDY"];

async function scanForHardcodedPaths(cloneDir) {
  const targets = [
    path.join(cloneDir, "tools", "build_mock_workbench_data.mjs"),
    path.join(cloneDir, "tools", "start_demo_stack.ps1"),
    path.join(cloneDir, "tools", "start_mock_workbench_runtime.ps1"),
    path.join(cloneDir, "config", "runtime_observability.yaml"),
    path.join(cloneDir, "docs", "production_readiness_audit.md"),
    path.join(cloneDir, "docs", "production_readiness_defects.md"),
    path.join(cloneDir, "docs", "production_readiness_final_report.md"),
    path.join(cloneDir, "docs", "three_track_known_limitations.md"),
  ];
  const hits = [];
  for (const filePath of targets) {
    const source = await fs.readFile(filePath, "utf8");
    for (const pattern of hardcodedPathPatterns) {
      if (source.includes(pattern)) {
        hits.push({
          file: path.relative(cloneDir, filePath).replace(/\\/g, "/"),
          pattern,
        });
      }
    }
  }
  return hits;
}

async function writeLog(outputDir, name, result) {
  const logPath = path.join(outputDir, `${name}.log.txt`);
  const payload = [
    `# ${name}`,
    ``,
    `command: ${result.command}`,
    `cwd: ${result.cwd}`,
    `exitCode: ${result.code}`,
    ``,
    `## stdout`,
    result.stdout || "",
    ``,
    `## stderr`,
    result.stderr || "",
  ].join("\n");
  await fs.writeFile(logPath, payload, "utf8");
  return logPath;
}

async function runCommand(outputDir, name, command, args, cwd, extra = {}) {
  const result = await runProcess(command, args, {
    cwd,
    env: extra.env || {},
  });
  result.command = `${command} ${args.join(" ")}`.trim();
  result.cwd = cwd;
  result.logPath = await writeLog(outputDir, name, result);
  return result;
}

async function latestReportJson(rootDir, prefix, fileName) {
  const entries = await fs.readdir(rootDir, { withFileTypes: true });
  const candidates = [];
  for (const entry of entries) {
    if (!entry.isDirectory() || !entry.name.startsWith(prefix)) {
      continue;
    }
    const fullPath = path.join(rootDir, entry.name);
    const stat = await fs.stat(fullPath);
    candidates.push({ fullPath, name: entry.name, mtimeMs: stat.mtimeMs });
  }
  candidates.sort((left, right) => right.mtimeMs - left.mtimeMs);
  if (!candidates.length) {
    return null;
  }
  const chosen = candidates[0];
  const reportPath = path.join(chosen.fullPath, fileName);
  const report = JSON.parse(await fs.readFile(reportPath, "utf8"));
  return {
    directory: chosen.name,
    reportPath,
    report,
  };
}

async function main() {
  const runId = makeRunId("clean_reproduction");
  const outputDir = path.join(workspaceRoot, "outputs", "final_review", runId);
  const cloneDir = path.join(tempRoot, `${runId}_clone`);
  await ensureDir(outputDir);
  await fs.rm(cloneDir, { recursive: true, force: true });

  const headResult = await runCommand(outputDir, "git_head", "git", ["rev-parse", "HEAD"], workspaceRoot);
  if (headResult.code !== 0) {
    throw new Error("clean_reproduction_failed_to_read_head");
  }
  const commit = headResult.stdout.trim();

  const cloneResult = await runCommand(
    outputDir,
    "git_clone",
    "git",
    ["clone", "--no-local", workspaceRoot, cloneDir],
    workspaceRoot
  );
  if (cloneResult.code !== 0) {
    throw new Error("clean_reproduction_clone_failed");
  }

  const checkoutResult = await runCommand(
    outputDir,
    "git_checkout",
    "git",
    ["checkout", commit],
    cloneDir
  );
  if (checkoutResult.code !== 0) {
    throw new Error("clean_reproduction_checkout_failed");
  }

  const statusResult = await runCommand(outputDir, "git_status", "git", ["status", "--short"], cloneDir);
  const stashResult = await runCommand(outputDir, "git_stash_list", "git", ["stash", "list"], cloneDir);
  const untrackedResult = await runCommand(
    outputDir,
    "git_untracked",
    "git",
    ["ls-files", "--others", "--exclude-standard"],
    cloneDir
  );
  const nodeResult = await runCommand(outputDir, "node_version", process.execPath, ["-v"], cloneDir);
  const npmCiResult = await runCommand(outputDir, "npm_ci", npmCommand, ["ci"], cloneDir);
  if (npmCiResult.code !== 0) {
    throw new Error("clean_reproduction_npm_ci_failed");
  }

  const baselineResult = await runCommand(
    outputDir,
    "three_track_baseline",
    npmCommand,
    ["run", "test:three-track-baseline"],
    cloneDir
  );
  if (baselineResult.code !== 0) {
    throw new Error("clean_reproduction_three_track_baseline_failed");
  }

  const postgresLiveResult = await runCommand(
    outputDir,
    "postgres_live",
    npmCommand,
    ["run", "test:postgres-live"],
    cloneDir
  );
  if (postgresLiveResult.code !== 0) {
    throw new Error("clean_reproduction_postgres_live_failed");
  }

  const backupRestoreResult = await runCommand(
    outputDir,
    "backup_restore",
    npmCommand,
    ["run", "test:backup-restore"],
    cloneDir
  );
  if (backupRestoreResult.code !== 0) {
    throw new Error("clean_reproduction_backup_restore_failed");
  }

  const productionResult = await runCommand(
    outputDir,
    "production_readiness",
    npmCommand,
    ["run", "test:production-readiness"],
    cloneDir
  );

  const reportsRoot = path.join(cloneDir, "outputs", "production_readiness");
  const baselineReport = await latestReportJson(
    reportsRoot,
    "three_track_validation_baseline_",
    "three_track_validation_baseline_report.json"
  );
  const productionReport = await latestReportJson(
    reportsRoot,
    "production_readiness_",
    "production_readiness_report.json"
  );

  if (baselineReport?.report?.summary?.finalStatus !== "VALIDATION_BASELINE_READY") {
    throw new Error("clean_reproduction_baseline_status_mismatch");
  }
  if (productionReport?.report?.summary?.finalStatus !== "NOT_READY") {
    throw new Error("clean_reproduction_production_status_mismatch");
  }
  if (productionResult.code === 0) {
    throw new Error("clean_reproduction_production_gate_should_not_be_ready");
  }

  const gitStatusShort = statusResult.stdout.trim();
  const gitStashList = stashResult.stdout.trim();
  const untrackedFiles = untrackedResult.stdout.trim().split(/\r?\n/).filter(Boolean);
  if (gitStatusShort) {
    throw new Error("clean_reproduction_git_status_not_empty");
  }
  if (gitStashList) {
    throw new Error("clean_reproduction_stash_should_be_empty");
  }
  if (untrackedFiles.length > 0) {
    throw new Error("clean_reproduction_untracked_files_present");
  }

  const backupPathExists = await fs
    .access(path.join(cloneDir, "outputs", "git_safety_backup_20260624"))
    .then(() => true)
    .catch(() => false);
  if (backupPathExists) {
    throw new Error("clean_reproduction_should_not_contain_git_safety_backup");
  }

  const hardcodedPathHits = await scanForHardcodedPaths(cloneDir);
  if (hardcodedPathHits.length > 0) {
    throw new Error("clean_reproduction_hardcoded_path_hits_found");
  }

  const summary = {
    commit,
    nodeVersion: nodeResult.stdout.trim(),
    os: process.platform,
    cloneDir,
    gitStatusShort,
    gitStashList,
    untrackedFiles,
    backupPathExists,
    hardcodedPathHits,
    baseline: {
      exitCode: baselineResult.code,
      finalStatus: baselineReport.report.summary.finalStatus,
      reportDir: baselineReport.directory,
      postgresVersion: baselineReport.report.environment.postgresVersion,
    },
    postgresLive: {
      exitCode: postgresLiveResult.code,
    },
    backupRestore: {
      exitCode: backupRestoreResult.code,
    },
    productionReadiness: {
      exitCode: productionResult.code,
      finalStatus: productionReport.report.summary.finalStatus,
      reportDir: productionReport.directory,
      postgresVersion: productionReport.report.environment.postgresVersion,
    },
    logDir: outputDir,
  };

  await fs.writeFile(
    path.join(outputDir, "clean_reproduction_summary.json"),
    JSON.stringify(summary, null, 2),
    "utf8"
  );
  await fs.writeFile(
    path.join(workspaceRoot, "docs", "three_track_clean_reproduction_report.md"),
    [
      "# Three-Track Clean Reproduction Report",
      "",
      `Updated: ${new Date().toISOString()}`,
      "",
      `- Commit: \`${summary.commit}\``,
      `- Node: \`${summary.nodeVersion}\``,
      `- OS: \`${summary.os}\``,
      `- Clean clone directory: \`${summary.cloneDir}\``,
      `- git status --short: \`${summary.gitStatusShort || "(empty)"}\``,
      `- git stash list: \`${summary.gitStashList || "(empty)"}\``,
      `- git-safety backup present in clone: \`${summary.backupPathExists}\``,
      `- Untracked files in clone: \`${summary.untrackedFiles.length}\``,
      `- Hardcoded local path hits in audited files: \`${summary.hardcodedPathHits.length}\``,
      "",
      "## Command Results",
      `- \`npm ci\`: exit ${npmCiResult.code}`,
      `- \`npm run test:three-track-baseline\`: exit ${baselineResult.code}, status \`${summary.baseline.finalStatus}\`, PostgreSQL \`${summary.baseline.postgresVersion}\``,
      `- \`npm run test:postgres-live\`: exit ${postgresLiveResult.code}`,
      `- \`npm run test:backup-restore\`: exit ${backupRestoreResult.code}`,
      `- \`npm run test:production-readiness\`: exit ${productionResult.code}, status \`${summary.productionReadiness.finalStatus}\`, PostgreSQL \`${summary.productionReadiness.postgresVersion}\``,
      "",
      "## Report Directories",
      `- Three-track baseline: \`${summary.baseline.reportDir}\``,
      `- Production readiness: \`${summary.productionReadiness.reportDir}\``,
      "",
      `Detailed logs: \`${outputDir}\``,
    ].join("\n"),
    "utf8"
  );

  await fs.rm(cloneDir, { recursive: true, force: true });
  process.stdout.write(`${JSON.stringify({ ok: true, summary }, null, 2)}\n`);
}

main().catch((error) => {
  // Exit explicitly after stderr flush so review runners cannot misclassify a failed reproduction as pass.
  process.stderr.write(
    `${JSON.stringify({ ok: false, error: String(error?.message || error) }, null, 2)}\n`,
    () => process.exit(1)
  );
});
