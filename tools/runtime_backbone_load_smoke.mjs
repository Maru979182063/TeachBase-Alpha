/**
 * Purpose:
 * - Thin CLI wrapper that runs smoke-load checks.
 * - Use this as the quick operational probe before deeper soak or benchmark runs.
 */

import { runProductionReadiness } from "./runtime_backbone_production_readiness.mjs";

const report = await runProductionReadiness({
  runId: "load_smoke_checks",
  suites: new Set(["performance"]),
});

process.exitCode = report.summary.failed > 0 ? 1 : 0;
