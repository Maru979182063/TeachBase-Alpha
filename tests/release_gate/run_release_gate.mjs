import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

import {
  SkipTestError,
  createHarness,
  makeRunId,
  runProcess,
  workspaceRoot,
} from "../helpers/runtime_testkit.mjs";

const releaseGateRoot = path.join(
  workspaceRoot,
  "outputs",
  "test_runs",
  "release_gate"
);

const moduleConfigs = [
  {
    id: "release_gate_preflight",
    path: path.join(workspaceRoot, "tests", "release_gate", "00_preflight_env.test.mjs"),
  },
  {
    id: "release_gate_migration",
    path: path.join(workspaceRoot, "tests", "release_gate", "01_migration_schema.test.mjs"),
  },
  {
    id: "migrations",
    path: path.join(workspaceRoot, "tests", "migrations", "postgres_migration_checks.mjs"),
  },
  {
    id: "release_gate_backup_restore",
    path: path.join(workspaceRoot, "tests", "release_gate", "02_backup_restore.test.mjs"),
    heavy: true,
  },
  {
    id: "static",
    path: path.join(workspaceRoot, "tests", "unit", "static_checks.mjs"),
  },
  {
    id: "release_gate_source_refs",
    path: path.join(workspaceRoot, "tests", "release_gate", "04_source_refs_merge.test.mjs"),
  },
  {
    id: "release_gate_qvs",
    path: path.join(workspaceRoot, "tests", "release_gate", "05_question_visual_structure.test.mjs"),
  },
  {
    id: "release_gate_asset_resolver",
    path: path.join(workspaceRoot, "tests", "release_gate", "06_asset_resolver.test.mjs"),
  },
  {
    id: "release_gate_decision",
    path: path.join(workspaceRoot, "tests", "release_gate", "07_release_decision.test.mjs"),
  },
  {
    id: "artifact_lineage",
    path: path.join(workspaceRoot, "tests", "release_gate", "08_artifact_lineage.test.mjs"),
  },
  {
    id: "business",
    path: path.join(workspaceRoot, "tests", "business", "runtime_business_checks.mjs"),
  },
  {
    id: "api",
    path: path.join(workspaceRoot, "tests", "api", "runtime_api_e2e.mjs"),
  },
  {
    id: "release_gate_visual_adapter",
    path: path.join(workspaceRoot, "tests", "release_gate", "08_visual_split_adapter.test.mjs"),
  },
  {
    id: "store_contract",
    path: path.join(workspaceRoot, "tests", "store-contract", "file_and_postgres_contracts.mjs"),
  },
  {
    id: "three_track",
    path: path.join(workspaceRoot, "tests", "three-track", "runtime_three_track_baseline.mjs"),
    heavy: true,
  },
  {
    id: "projection_read_path",
    path: path.join(workspaceRoot, "tests", "projection", "runtime_projection_read_path_checks.mjs"),
  },
  {
    id: "postgres_sole_source",
    path: path.join(workspaceRoot, "tests", "postgres-sole-source", "runtime_postgres_sole_source.mjs"),
  },
  {
    id: "postgres_sole_source_full",
    path: path.join(workspaceRoot, "tests", "postgres-sole-source", "runtime_postgres_sole_source_full.mjs"),
    heavy: true,
  },
  {
    id: "failure_injection",
    path: path.join(workspaceRoot, "tests", "failure-injection", "runtime_failure_checks.mjs"),
  },
  {
    id: "security",
    path: path.join(workspaceRoot, "tests", "security", "runtime_security_checks.mjs"),
  },
  {
    id: "release_gate_concurrency",
    path: path.join(workspaceRoot, "tests", "release_gate", "13_concurrency_idempotency.test.mjs"),
  },
  {
    id: "release_gate_html",
    path: path.join(workspaceRoot, "tests", "release_gate", "14_html_externalization.test.mjs"),
  },
  {
    id: "compat",
    path: path.join(workspaceRoot, "tests", "compat", "runtime_compat_proxy_checks.mjs"),
  },
  {
    id: "release_gate_legacy",
    path: path.join(workspaceRoot, "tests", "release_gate", "15_legacy_regression.test.mjs"),
  },
  {
    id: "audit",
    path: path.join(workspaceRoot, "tests", "audit", "runtime_architecture_gate.mjs"),
  },
  {
    id: "release_gate_performance",
    path: path.join(workspaceRoot, "tests", "release_gate", "16_performance_smoke.test.mjs"),
    heavy: true,
    performance: true,
  },
];

function parseArgs(argv) {
  return {
    fast: argv.includes("--fast"),
    full: argv.includes("--full") || !argv.includes("--fast"),
    withDocker: argv.includes("--with-docker"),
    skipPerformance: argv.includes("--skip-performance"),
    reportJson: argv.includes("--report-json"),
    reportMd: argv.includes("--report-md"),
  };
}

function severityForTest(testCase) {
  if (testCase.required === false) {
    return "P1";
  }
  if (
    testCase.suite === "release_gate_performance" ||
    testCase.suite === "performance"
  ) {
    return "P1";
  }
  return "P0";
}

async function loadCases(options) {
  const modules = moduleConfigs.filter((config) => {
    if (options.skipPerformance && config.performance) {
      return false;
    }
    if (options.fast && config.heavy) {
      return false;
    }
    return true;
  });
  const cases = [];
  const register = (testCase) => {
    cases.push({
      ...testCase,
      severity: testCase.severity || severityForTest(testCase),
    });
  };
  for (const config of modules) {
    const imported = await import(
      `${pathToFileURL(config.path).href}?run=${Date.now()}_${Math.random()}`
    );
    imported.registerTests(register);
  }
  return cases;
}

function renderMarkdown(report) {
  const failed = report.results.filter((item) => item.status === "failed");
  const skipped = report.results.filter((item) => item.status === "skipped");
  const warnings = report.warnings;
  return [
    "# Release Gate 测试结果",
    "",
    "## 1. 总结论",
    `- 结论：${report.summary.verdict}`,
    `- P0 blocker：${report.summary.p0BlockerCount}`,
    `- P1 warning：${report.summary.p1WarningCount}`,
    "",
    "## 2. 已新增测试文件",
    ...report.addedFiles.map((file) => `- ${file}`),
    "",
    "## 3. 已覆盖风险",
    ...report.coveredRisks.map((item) => `- ${item}`),
    "",
    "## 4. 未覆盖风险",
    ...(report.uncoveredRisks.length
      ? report.uncoveredRisks.map((item) => `- ${item}`)
      : ["- 无新增未覆盖风险记录，本轮剩余问题均进入 P0/P1 列表。"]),
    "",
    "## 5. 运行命令",
    `- node tests/release_gate/run_release_gate.mjs ${report.commandLine}`,
    "",
    "## 6. 实际运行结果",
    `- Git commit hash：${report.environment.gitCommit}`,
    `- Migration list：${report.environment.migrations.join(", ")}`,
    `- Test DB name：${report.environment.createdDatabases.join(", ") || "none"}`,
    `- Total pass/fail/skip：${report.summary.passed}/${report.summary.failed}/${report.summary.skipped}`,
    `- Report dir：${report.environment.reportDir}`,
    "",
    "## 7. P0 blocker 详情",
    ...(report.p0Blockers.length
      ? report.p0Blockers.map(
          (item) => `- ${item.id} [${item.suite}] ${item.title}: ${item.error}`
        )
      : ["- 无"]),
    "",
    "## 8. P1 warning 详情",
    ...((report.p1FollowUps.length || warnings.length)
      ? [
          ...report.p1FollowUps.map(
            (item) => `- ${item.id} [${item.suite}] ${item.title}: ${item.error}`
          ),
          ...warnings.map((warning) => `- ${warning}`),
        ]
      : ["- 无"]),
    "",
    "## 9. 需要人工确认的问题",
    "- question_uid 规则：当前仍依赖运行时和视觉清单共同保证稳定命名，尚未升格为数据库约束。",
    "- storage_key 版本化规则：现已验证需要包含 runtime_run_id 段，避免同题重跑覆盖旧图。",
    "- evidence_only 展示策略：正式导出继续排除，审核 HTML 允许展示。",
    "- 旧 stem 人工编辑策略：当前仍以 legacy_stem_md 兼容投影为主，人工编辑回写策略未在本轮扩展。",
    "- artifact status 语义：integrity/logical/lifecycle 三状态仍并存，语义未完全收口。",
    "- job_attempt lease_token：本轮未补列，继续作为 P1 架构性告警。",
    "",
    "## 10. 生产建议",
    `- ${report.summary.verdict}`,
    "",
    "## Failures",
    ...(failed.length
      ? failed.map(
          (item) => `- ${item.id} [${item.suite}] ${item.title}: ${item.error}`
        )
      : ["- 无"]),
    "",
    "## Skipped",
    ...(skipped.length
      ? skipped.map(
          (item) => `- ${item.id} [${item.suite}] ${item.title}: ${item.error}`
        )
      : ["- 无"]),
  ].join("\n");
}

async function collectEnvironment(harness, runId) {
  const [gitCommit, gitBranch, migrations] = await Promise.all([
    runProcess("git", ["rev-parse", "HEAD"]),
    runProcess("git", ["branch", "--show-current"]),
    fs.readdir(path.join(workspaceRoot, "config", "migrations")),
  ]);
  return {
    runId,
    gitCommit: gitCommit.code === 0 ? gitCommit.stdout.trim() : "unknown",
    gitBranch: gitBranch.code === 0 ? gitBranch.stdout.trim() : "unknown",
    nodeVersion: process.version,
    reportDir: path.relative(workspaceRoot, harness.outputDir),
    migrations: migrations.filter((name) => name.endsWith(".sql")).sort(),
    createdDatabases: [],
  };
}

export async function runReleaseGate(argv = process.argv.slice(2)) {
  const options = parseArgs(argv);
  if (options.withDocker) {
    process.env.RELEASE_GATE_REQUIRE_DOCKER = "true";
  }
  const runId = makeRunId("release_gate");
  const harness = await createHarness({
    runId,
    reportRoot: releaseGateRoot,
  });
  const startedAt = Date.now();
  try {
    const cases = await loadCases(options);
    const environment = await collectEnvironment(harness, runId);
    const results = [];
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

    environment.createdDatabases = [...new Set(harness.createdDatabases)];
    const warnings = results.flatMap((item) =>
      Array.isArray(item.detail?.warnings)
        ? item.detail.warnings.map(
            (warning) => `${item.id} [${item.suite}]: ${warning}`
          )
        : []
    );
    const p0Blockers = results.filter(
      (item) => item.status === "failed" && item.severity === "P0"
    );
    const p1FollowUps = results.filter(
      (item) =>
        (item.status === "failed" && item.severity !== "P0") ||
        item.status === "skipped"
    );
    const verdict =
      p0Blockers.length > 0
        ? "NO-GO"
        : p1FollowUps.length > 0 || warnings.length > 0
          ? "GO WITH WARNINGS"
          : "GO";
    const report = {
      commandLine: argv.join(" ").trim() || "--full --report-json --report-md",
      environment,
      summary: {
        total: results.length,
        passed: results.filter((item) => item.status === "passed").length,
        failed: results.filter((item) => item.status === "failed").length,
        skipped: results.filter((item) => item.status === "skipped").length,
        durationMs: Date.now() - startedAt,
        verdict,
        p0BlockerCount: p0Blockers.length,
        p1WarningCount: p1FollowUps.length + warnings.length,
      },
      addedFiles: moduleConfigs
        .filter((item) => item.path.includes(`${path.sep}tests${path.sep}release_gate${path.sep}`))
        .map((item) => path.relative(workspaceRoot, item.path))
        .filter((item) => item.endsWith(".test.mjs")),
      coveredRisks: [
        "环境预检与测试库安全边界",
        "Migration / schema 快照一致性",
        "备份恢复与恢复后导出可用性",
        "source_refs_json merge 保真",
        "question_visual_structure.v1.1 契约",
        "asset:// resolver 安全校验",
        "视觉拆题 Adapter 落库边界",
        "导入 / 审核 / 发布 / 题库 / material / export / rerun 现有回归链路",
        "并发幂等与 storage_key 版本化",
        "HTML 外化审核视图",
        "Legacy no-QVS 导出回归",
        "多轨道性能 smoke",
      ],
      uncoveredRisks: [],
      results,
      warnings,
      p0Blockers,
      p1FollowUps,
    };

    await fs.mkdir(harness.outputDir, { recursive: true });
    const jsonPath = path.join(harness.outputDir, "report.json");
    const mdPath = path.join(harness.outputDir, "report.md");
    await fs.writeFile(jsonPath, JSON.stringify(report, null, 2), "utf8");
    await fs.writeFile(mdPath, renderMarkdown(report), "utf8");

    if (options.reportJson && !options.reportMd) {
      process.stdout.write(`${jsonPath}\n`);
    } else if (options.reportMd && !options.reportJson) {
      process.stdout.write(`${mdPath}\n`);
    } else {
      process.stdout.write(`${jsonPath}\n${mdPath}\n`);
    }
    return report;
  } finally {
    await harness.dispose();
  }
}

if (import.meta.url === pathToFileURL(path.resolve(process.argv[1] || "")).href) {
  const report = await runReleaseGate();
  process.exit(report.summary.p0BlockerCount > 0 ? 1 : 0);
}
