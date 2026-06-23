/**
 * Purpose:
 * - Thin CLI wrapper that runs the soak suite.
 * - Keep long-running soak orchestration lightweight here and detailed scenarios in the tests.
 */

import { runProductionReadiness } from "./runtime_backbone_production_readiness.mjs";

const report = await runProductionReadiness({
  runId: "soak_checks",
  suites: new Set(["performance"]),
});

process.exitCode = report.summary.failed > 0 ? 1 : 0;
