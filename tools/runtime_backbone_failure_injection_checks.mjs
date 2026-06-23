import { runProductionReadiness } from "./runtime_backbone_production_readiness.mjs";

const report = await runProductionReadiness({
  runId: "failure_injection_checks",
  suites: new Set(["failure_injection"]),
});

process.exitCode = report.summary.failed > 0 ? 1 : 0;
