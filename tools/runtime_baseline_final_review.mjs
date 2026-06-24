/**
 * Purpose:
 * - run the independent final review for the three-track validation baseline
 * - keep the validation result, the production-policy result, and the clean-clone proof separate
 */

import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import {
  SkipTestError,
  createHarness,
  makeRunId,
  reportRoot,
  runProcess,
  workspaceRoot,
} from "../tests/helpers/runtime_testkit.mjs";

const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";

const modulePaths = [
  path.join(workspaceRoot, "tests", "unit", "static_checks.mjs"),
  path.join(workspaceRoot, "tests", "compat", "runtime_compat_proxy_checks.mjs"),
  path.join(workspaceRoot, "tests", "migrations", "postgres_migration_checks.mjs"),
  path.join(workspaceRoot, "tests", "store-contract", "file_and_postgres_contracts.mjs"),
  path.join(workspaceRoot, "tests", "api", "runtime_api_e2e.mjs"),
  path.join(workspaceRoot, "tests", "business", "runtime_business_checks.mjs"),
  path.join(workspaceRoot, "tests", "projection", "runtime_projection_read_path_checks.mjs"),
  path.join(workspaceRoot, "tests", "postgres-sole-source", "runtime_postgres_sole_source.mjs"),
  path.join(workspaceRoot, "tests", "postgres-sole-source", "runtime_postgres_sole_source_full.mjs"),
  path.join(workspaceRoot, "tests", "failure-injection", "runtime_failure_checks.mjs"),
  path.join(workspaceRoot, "tests", "backup-restore", "runtime_backup_restore.mjs"),
  path.join(workspaceRoot, "tests", "three-track", "runtime_three_track_baseline.mjs"),
];

function escapeXml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function renderJUnit(report) {
  const testcases = report.internalResults
    .map((result) => {
      const attrs = `classname="${result.suite}" name="${result.id} ${escapeXml(result.title)}" time="${(result.durationMs / 1000).toFixed(3)}"`;
      if (result.status === "passed") {
        return `    <testcase ${attrs} />`;
      }
      if (result.status === "skipped") {
        return `    <testcase ${attrs}><skipped message="${escapeXml(result.error || "skipped")}" /></testcase>`;
      }
      return `    <testcase ${attrs}><failure message="${escapeXml(result.error || "failed")}">${escapeXml(JSON.stringify(result.detail || {}, null, 2))}</failure></testcase>`;
    })
    .join("\n");
  return [
    `<?xml version="1.0" encoding="UTF-8"?>`,
    `<testsuite name="runtime_baseline_final_review" tests="${report.summary.internalTotal}" failures="${report.summary.internalFailed + report.summary.externalFailed}" skipped="${report.summary.internalSkipped}" time="${(report.summary.durationMs / 1000).toFixed(3)}">`,
    testcases,
    `</testsuite>`,
  ].join("\n");
}

async function loadCases() {
  const cases = [];
  const register = (testCase) => {
    cases.push(testCase);
  };
  for (const modulePath of modulePaths) {
    const module = await import(`${pathToFileURL(modulePath).href}?run=${Date.now()}_${Math.random()}`);
    module.registerTests(register);
  }
  return cases;
}

async function latestReportJson(rootDir, prefix, fileName) {
  const entries = await fs.readdir(rootDir, { withFileTypes: true }).catch(() => []);
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

async function runCommand(outputDir, name, command, args) {
  const result = await runProcess(command, args, { cwd: workspaceRoot });
  const payload = [
    `# ${name}`,
    ``,
    `command: ${command} ${args.join(" ")}`,
    `exitCode: ${result.code}`,
    ``,
    `## stdout`,
    result.stdout || "",
    ``,
    `## stderr`,
    result.stderr || "",
  ].join("\n");
  await fs.writeFile(path.join(outputDir, `${name}.log.txt`), payload, "utf8");
  return result;
}

function evaluateProductionGate(result, reportInfo) {
  if (!reportInfo?.report) {
    return {
      ok: false,
      detail: "production_readiness_report_missing",
    };
  }
  const report = reportInfo.report;
  const failures = report.results.filter((item) => item.status === "failed");
  if (result.code === 0) {
    return {
      ok: false,
      detail: "production_readiness_should_not_exit_zero",
    };
  }
  if (report.summary.finalStatus !== "NOT_READY") {
    return {
      ok: false,
      detail: `production_readiness_status_mismatch:${report.summary.finalStatus}`,
    };
  }
  if (failures.length !== 1 || failures[0].id !== "POLICY-001") {
    return {
      ok: false,
      detail: `production_readiness_unexpected_failures:${failures.map((item) => item.id).join(",")}`,
    };
  }
  if (failures[0].error !== "validation_baseline_must_not_claim_production_ready") {
    return {
      ok: false,
      detail: `production_readiness_policy_error_mismatch:${failures[0].error}`,
    };
  }
  return {
    ok: true,
    detail: {
      finalStatus: report.summary.finalStatus,
      failedGate: failures[0].id,
      runId: report.environment.runId,
    },
  };
}

async function collectEnvironment(harness, runId) {
  const gitCommit = await runProcess("git", ["rev-parse", "HEAD"]);
  const gitBranch = await runProcess("git", ["branch", "--show-current"]);
  return {
    runId,
    nodeVersion: process.version,
    platform: process.platform,
    gitCommit: gitCommit.code === 0 ? gitCommit.stdout.trim() : "unknown",
    gitBranch: gitBranch.code === 0 ? gitBranch.stdout.trim() : "unknown",
    startedAt: new Date().toISOString(),
    reportRoot,
    postgresVersion: harness.postgresCluster?.version || null,
  };
}

export async function runBaselineFinalReview() {
  const runId = makeRunId("baseline_final_review");
  const harness = await createHarness({ runId });
  const outputDir = harness.outputDir;
  const startedAt = Date.now();
  const internalResults = [];
  const externalChecks = [];

  try {
    const cases = await loadCases();
    const environment = await collectEnvironment(harness, runId);

    for (const testCase of cases) {
      const caseStartedAt = Date.now();
      process.stdout.write(`[${testCase.suite}] ${testCase.id} ${testCase.title} ... `);
      try {
        const detail = await testCase.run({
          harness,
          workspaceRoot,
          outputDir,
        });
        internalResults.push({
          ...testCase,
          status: "passed",
          durationMs: Date.now() - caseStartedAt,
          detail: detail || null,
          error: null,
        });
        process.stdout.write("PASS\n");
      } catch (error) {
        const status = error instanceof SkipTestError ? "skipped" : "failed";
        internalResults.push({
          ...testCase,
          status,
          durationMs: Date.now() - caseStartedAt,
          detail: error?.detail || null,
          error: error?.message || String(error),
        });
        process.stdout.write(`${status.toUpperCase()}\n`);
      }
    }

    const reportsPath = path.join(workspaceRoot, "outputs", "production_readiness");

    const baselineResult = await runCommand(outputDir, "three_track_baseline", npmCommand, [
      "run",
      "test:three-track-baseline",
    ]);
    const baselineReport = await latestReportJson(
      reportsPath,
      "three_track_validation_baseline_",
      "three_track_validation_baseline_report.json"
    );
    externalChecks.push({
      name: "three_track_baseline",
      exitCode: baselineResult.code,
      ok:
        baselineResult.code === 0 &&
        baselineReport?.report?.summary?.finalStatus === "VALIDATION_BASELINE_READY",
      detail: baselineReport
        ? {
            finalStatus: baselineReport.report.summary.finalStatus,
            runId: baselineReport.report.environment.runId,
          }
        : "three_track_baseline_report_missing",
    });

    const postgresLiveResult = await runCommand(outputDir, "postgres_live", npmCommand, [
      "run",
      "test:postgres-live",
    ]);
    externalChecks.push({
      name: "postgres_live",
      exitCode: postgresLiveResult.code,
      ok: postgresLiveResult.code === 0,
      detail: postgresLiveResult.code === 0 ? "ok" : "postgres_live_failed",
    });

    const productionResult = await runCommand(outputDir, "production_readiness", npmCommand, [
      "run",
      "test:production-readiness",
    ]);
    const productionReport = await latestReportJson(
      reportsPath,
      "production_readiness_",
      "production_readiness_report.json"
    );
    const productionEvaluation = evaluateProductionGate(productionResult, productionReport);
    externalChecks.push({
      name: "production_readiness",
      exitCode: productionResult.code,
      ok: productionEvaluation.ok,
      detail: productionEvaluation.detail,
    });

    const cleanReproResult = await runCommand(outputDir, "clean_reproduction", process.execPath, [
      path.join(workspaceRoot, "tools", "runtime_clean_reproduction_check.mjs"),
    ]);
    const cleanReproductionSummaryPath = path.join(
      workspaceRoot,
      "docs",
      "three_track_clean_reproduction_report.md"
    );
    externalChecks.push({
      name: "clean_reproduction",
      exitCode: cleanReproResult.code,
      ok: cleanReproResult.code === 0,
      detail: cleanReproResult.code === 0 ? cleanReproductionSummaryPath : "clean_reproduction_failed",
    });

    environment.postgresVersion = harness.postgresCluster?.version || null;

    const summary = {
      internalTotal: internalResults.length,
      internalPassed: internalResults.filter((item) => item.status === "passed").length,
      internalFailed: internalResults.filter((item) => item.status === "failed").length,
      internalSkipped: internalResults.filter((item) => item.status === "skipped").length,
      externalTotal: externalChecks.length,
      externalFailed: externalChecks.filter((item) => !item.ok).length,
      durationMs: Date.now() - startedAt,
    };
    summary.finalStatus =
      summary.internalFailed === 0 && summary.externalFailed === 0
        ? "BASELINE_FINAL_REVIEW_PASSED"
        : "BASELINE_FINAL_REVIEW_FAILED";

    const report = {
      environment,
      summary,
      internalResults,
      externalChecks,
    };

    await fs.writeFile(
      path.join(outputDir, "baseline_final_review_report.json"),
      JSON.stringify(report, null, 2),
      "utf8"
    );
    await fs.writeFile(
      path.join(outputDir, "baseline_final_review_junit.xml"),
      renderJUnit(report),
      "utf8"
    );
    await fs.writeFile(
      path.join(outputDir, "baseline_final_review_summary.md"),
      [
        "# Baseline Final Review",
        "",
        `- Run ID: ${environment.runId}`,
        `- Git commit: ${environment.gitCommit}`,
        `- Git branch: ${environment.gitBranch}`,
        `- PostgreSQL: ${environment.postgresVersion || "not-started"}`,
        `- Internal passed: ${summary.internalPassed}/${summary.internalTotal}`,
        `- External passed: ${summary.externalTotal - summary.externalFailed}/${summary.externalTotal}`,
        `- Final status: ${summary.finalStatus}`,
        "",
        "## External Checks",
        ...externalChecks.map(
          (item) => `- ${item.name}: ${item.ok ? "PASS" : "FAIL"} (exit ${item.exitCode})`
        ),
      ].join("\n"),
      "utf8"
    );

    return report;
  } finally {
    await harness.dispose();
  }
}

const report = await runBaselineFinalReview();
process.stdout.write(`${report.summary.finalStatus}\n`);
process.exit(report.summary.finalStatus === "BASELINE_FINAL_REVIEW_PASSED" ? 0 : 1);
