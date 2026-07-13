/**
 * 用途：
 * - 覆盖运行时表面的权限、路径和不安全输入检查。
 * - 新增文件系统或 SQL 入口时，应在这里补安全覆盖。
 */

import {
  expect,
  readJsonFixture,
} from "../helpers/runtime_testkit.mjs";

export function registerTests(register) {
  register({
    id: "L03",
    suite: "security",
    title: "Approve should require role-aware authorization instead of a single shared admin token",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("math", "minimal_bundle.json");
      const server = await harness.startPostgresServer("security_authz_test");
      const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "ordinary_teacher",
          bundle: {
            ...bundle,
            bundle_id: `${bundle.bundle_id}_authz`,
            lesson_id: `${bundle.lesson_id}_authz`,
          },
        },
      });
      expect(imported.ok, "security_import_setup_failed");
      const approve = await server.request(
        `/api/runtime/review-tasks/${imported.data.result.reviewTaskId}/approve`,
        {
          method: "POST",
          body: {
            actor: "ordinary_teacher",
          },
        }
      );
      expect(
        approve.status === 403,
        `approve_authorization_missing:expected_403_actual_${approve.status}`
      );
      return {
        status: approve.status,
      };
    },
  });

  register({
    id: "L23",
    suite: "security",
    title: "Write-heavy endpoints should surface rate limiting under a burst",
    required: true,
    async run({ harness }) {
      const server = await harness.startFileServer("security_rate_limit_test");
      const responses = await Promise.all(
        Array.from({ length: 25 }, () =>
          server.request("/api/runtime/jobs/recover", {
            method: "POST",
            body: {
              actor: "burst_test",
            },
          })
        )
      );
      const limited = responses.filter((item) => item.status === 429).length;
      expect(limited > 0, "rate_limit_missing");
      return {
        limited,
        total: responses.length,
      };
    },
  });

  register({
    id: "L02",
    suite: "security",
    title: "Invalid admin token is rejected",
    required: true,
    async run({ harness }) {
      const server = await harness.startPostgresServer("security_token_test");
      const response = await server.request("/api/runtime/bootstrap", {
        method: "POST",
        body: {},
        headers: {
          "X-Runtime-Admin-Token": "definitely_wrong",
        },
      });
      expect(response.status === 403, `invalid_admin_token_status_mismatch:${response.status}`);
      return {
        status: response.status,
      };
    },
  });
}
