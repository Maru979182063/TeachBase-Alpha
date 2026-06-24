/**
 * 用途：
 * - 运行不依赖外部服务的静态仓库检查。
 * - 这个文件用于在重型套件启动前低成本捕获回归。
 */

import path from "node:path";
import {
  expect,
  listFiles,
  runProcess,
  workspaceRoot,
} from "../helpers/runtime_testkit.mjs";

export function registerTests(register) {
  register({
    id: "A01",
    suite: "static",
    title: "All runtime .mjs files pass node --check",
    required: true,
    async run() {
      const roots = [
        path.join(workspaceRoot, "tools"),
        path.join(workspaceRoot, "tests"),
      ];
      const files = [];
      for (const root of roots) {
        files.push(...(await listFiles(root, (candidate) => candidate.endsWith(".mjs"))));
      }
      const failures = [];
      for (const file of files.sort()) {
        const result = await runProcess(process.execPath, ["--check", file]);
        if (result.code !== 0) {
          failures.push({
            file: path.relative(workspaceRoot, file),
            stderr: result.stderr.trim(),
          });
        }
      }
      expect(failures.length === 0, `node_check_failed:${JSON.stringify(failures)}`);
      return {
        fileCount: files.length,
      };
    },
  });

  register({
    id: "A06",
    suite: "static",
    title: "File mode server starts cleanly",
    required: true,
    async run({ harness }) {
      const server = await harness.startFileServer("static_file_mode");
      const health = await server.request("/health");
      expect(health.ok, "file_health_not_ok");
      expect(health.data.runtimeMode === "file", "file_runtime_mode_mismatch");
      return {
        runtimeMode: health.data.runtimeMode,
        requestId: health.data.requestId,
      };
    },
  });

  register({
    id: "A07",
    suite: "static",
    title: "Unknown runtime store is rejected",
    required: true,
    async run() {
      const result = await runProcess(
        process.execPath,
        [path.join(workspaceRoot, "tools", "mock_workbench_api_server.mjs")],
        {
          env: {
            RUNTIME_STORE: "mystery",
          },
        }
      );
      expect(result.code !== 0, "unknown_store_should_fail");
      expect(
        `${result.stderr}\n${result.stdout}`.includes("unsupported_runtime_store:mystery"),
        "unknown_store_error_missing"
      );
      return {
        exitCode: result.code,
      };
    },
  });

  register({
    id: "A08",
    suite: "static",
    title: "Postgres mode without DATABASE_URL fails instead of falling back",
    required: true,
    async run() {
      const result = await runProcess(
        process.execPath,
        [path.join(workspaceRoot, "tools", "mock_workbench_api_server.mjs")],
        {
          env: {
            RUNTIME_STORE: "postgres",
            DATABASE_URL: "",
            DATABASE_URL_TEST: "",
            RUNTIME_BACKBONE_DATABASE_URL: "",
          },
        }
      );
      expect(result.code !== 0, "postgres_without_url_should_fail");
      expect(
        `${result.stderr}\n${result.stdout}`.includes("postgres_store_requires_DATABASE_URL"),
        "postgres_missing_url_error_missing"
      );
      expect(
        !`${result.stderr}\n${result.stdout}`.includes("mock_workbench_api listening"),
        "postgres_mode_should_not_fallback_to_file"
      );
      return {
        exitCode: result.code,
      };
    },
  });
}
