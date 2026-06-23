import { createRuntimeBackboneStore } from "./runtime_backbone_store_interface.mjs";

async function main() {
  const store = await createRuntimeBackboneStore({
    mode:
      process.env.RUNTIME_STORE ||
      (process.env.DATABASE_URL_TEST || process.env.RUNTIME_BACKBONE_DATABASE_URL ? "postgres" : "file"),
  });
  try {
    const detail = store.getConsistencyReport
      ? await store.getConsistencyReport()
      : {
          ok: false,
          status: "unsupported",
          mismatches: [{ reason: "consistency_report_not_supported" }],
        };
    process.stdout.write(`${JSON.stringify(detail, null, 2)}\n`);
    process.exitCode = detail.ok ? 0 : 1;
  } finally {
    if (store.close) {
      await store.close();
    }
  }
}

await main();
