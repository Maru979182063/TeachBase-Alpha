/**
 * 用途：
 * - 编排三轨验证基线所需的测试套件并输出机器可读报告。
 * - 这个脚本只回答 validation baseline 是否就绪，不替代生产 readiness。
 */

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  SkipTestError,
  createHarness,
  makeRunId,
  reportRoot,
  runProcess,
  workspaceRoot,
} from "../tests/helpers/runtime_testkit.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const modulePaths = [
  path.join(workspaceRoot, "tests", "unit", "static_checks.mjs"),
  path.join(workspaceRoot, "tests", "migrations", "postgres_migration_checks.mjs"),
  path.join(workspaceRoot, "tests", "store-contract", "file_and_postgres_contracts.mjs"),
  path.join(workspaceRoot, "tests", "api", "runtime_api_e2e.mjs"),
  path.join(workspaceRoot, "tests", "business", "runtime_business_checks.mjs"),
  path.join(workspaceRoot, "tests", "backup-restore", "runtime_backup_restore.mjs"),
  path.join(workspaceRoot, "tests", "three-track", "runtime_three_track_baseline.mjs"),
];

function parseSuites(argv) {
  const suiteArg = argv.find((item) => item.startsWith("--suite="));
  const raw = suiteArg ? suiteArg.slice("--suite=".length) : process.env.TEST_SUITES || "";
  return new Set(
    raw
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
  );
}

function escapeXml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function renderJUnit(report) {
  const testcases = report.results
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
    `<testsuite name="runtime_three_track_validation_baseline" tests="${report.summary.total}" failures="${report.summary.failed}" skipped="${report.summary.skipped}" time="${(report.summary.durationMs / 1000).toFixed(3)}">`,
    testcases,
    `</testsuite>`,
  ].join("\n");
}

async function loadCases(filterSuites) {
  const cases = [];
  const register = (testCase) => {
    if (filterSuites.size > 0 && !filterSuites.has(testCase.suite)) {
      return;
    }
    cases.push(testCase);
  };
  for (const modulePath of modulePaths) {
    const module = await import(`${pathToFileURL(modulePath).href}?run=${Date.now()}_${Math.random()}`);
    module.registerTests(register);
  }
  return cases;
}

function computeFinalStatus(results) {
  const requiredFailures = results.filter((item) => item.required && item.status === "failed");
  return requiredFailures.length > 0
    ? "VALIDATION_BASELINE_NOT_READY"
    : "VALIDATION_BASELINE_READY";
}

async function collectEnvironment(harness, runId, suites) {
  const gitCommit = await runProcess("git", ["rev-parse", "HEAD"]);
  const gitBranch = await runProcess("git", ["branch", "--show-current"]);
  return {
    runId,
    suites,
    nodeVersion: process.version,
    platform: process.platform,
    gitCommit: gitCommit.code === 0 ? gitCommit.stdout.trim() : "unknown",
    gitBranch: gitBranch.code === 0 ? gitBranch.stdout.trim() : "unknown",
    startedAt: new Date().toISOString(),
    reportRoot,
    postgresVersion: harness.postgresCluster?.version || null,
  };
}

export async function runThreeTrackValidationBaseline(options = {}) {
  const suites = options.suites || parseSuites(process.argv.slice(2));
  const runId = options.runId || makeRunId("three_track_validation_baseline");
  const harness = await createHarness({ runId });
  const startedAt = Date.now();
  const results = [];
  try {
    const cases = await loadCases(suites);
    const environment = await collectEnvironment(harness, runId, [...suites]);
    for (const testCase of cases) {
      const caseStartedAt = Date.now();
      process.stdout.write(`[${testCase.suite}] ${testCase.id} ${testCase.title} ... `);
      try {
        const detail = await testCase.run({
          harness,
          workspaceRoot,
          outputDir: harness.outputDir,
        });
        results.push({
          ...testCase,
          status: "passed",
          durationMs: Date.now() - caseStartedAt,
          detail: detail || null,
          error: null,
        });
        process.stdout.write("PASS\n");
      } catch (error) {
        const status = error instanceof SkipTestError ? "skipped" : "failed";
        results.push({
          ...testCase,
          status,
          durationMs: Date.now() - caseStartedAt,
          detail: error?.detail || null,
          error: error?.message || String(error),
        });
        process.stdout.write(`${status.toUpperCase()}\n`);
      }
    }

    environment.postgresVersion = harness.postgresCluster?.version || null;
    const summary = {
      total: results.length,
      passed: results.filter((item) => item.status === "passed").length,
      failed: results.filter((item) => item.status === "failed").length,
      skipped: results.filter((item) => item.status === "skipped").length,
      durationMs: Date.now() - startedAt,
      finalStatus: computeFinalStatus(results),
    };
    const report = { environment, summary, results };
    await fs.mkdir(harness.outputDir, { recursive: true });
    await fs.writeFile(
      path.join(harness.outputDir, "three_track_validation_baseline_report.json"),
      JSON.stringify(report, null, 2),
      "utf8"
    );
    await fs.writeFile(
      path.join(harness.outputDir, "three_track_validation_baseline_junit.xml"),
      renderJUnit(report),
      "utf8"
    );
    await fs.writeFile(
      path.join(harness.outputDir, "three_track_validation_baseline_summary.md"),
      [
        `# Three-Track Validation Baseline`,
        ``,
        `- Run ID: ${environment.runId}`,
        `- Git commit: ${environment.gitCommit}`,
        `- Git branch: ${environment.gitBranch}`,
        `- PostgreSQL: ${environment.postgresVersion || "not-started"}`,
        `- Total: ${summary.total}`,
        `- Passed: ${summary.passed}`,
        `- Failed: ${summary.failed}`,
        `- Skipped: ${summary.skipped}`,
        `- Final status: ${summary.finalStatus}`,
        ``,
        `## Failures`,
        ...results
          .filter((item) => item.status === "failed")
          .map((item) => `- ${item.id} ${item.title}: ${item.error}`),
      ].join("\n"),
      "utf8"
    );
    return report;
  } finally {
    await harness.dispose();
  }
}

const isMainModule =
  process.argv[1] &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;

if (isMainModule) {
  const report = await runThreeTrackValidationBaseline();
  process.exit(report.summary.failed > 0 ? 1 : 0);
}
