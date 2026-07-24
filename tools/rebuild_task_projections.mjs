/**
 * 用途：
 * - 提供显式的 task_projection 重建入口，避免 GET 搜索路径隐式写库。
 * - 支持按 lesson_id、lesson_revision_id 或全量重建，方便运维和最终复核。
 */

import { createRuntimeBackboneStore } from "./runtime_backbone_store_interface.mjs";

function parseArgs(argv) {
  const args = {
    lessonId: null,
    lessonRevisionId: null,
  };
  for (const entry of argv) {
    if (entry.startsWith("--lesson-id=")) {
      args.lessonId = entry.slice("--lesson-id=".length);
      continue;
    }
    if (entry.startsWith("--lesson-revision-id=")) {
      args.lessonRevisionId = entry.slice("--lesson-revision-id=".length);
    }
  }
  return args;
}

const store = await createRuntimeBackboneStore();
try {
  const args = parseArgs(process.argv.slice(2));
  const result = await store.rebuildTaskProjections(args);
  process.stdout.write(`${JSON.stringify({ ok: true, result }, null, 2)}\n`);
} catch (error) {
  process.stderr.write(
    `${JSON.stringify({ ok: false, error: String(error?.message || error) }, null, 2)}\n`
  );
  process.exitCode = 1;
} finally {
  if (store.close) {
    await store.close();
  }
}
