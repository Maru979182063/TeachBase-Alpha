/**
 * 用途：
 * - 注册针对运行时主干 HTTP 服务的端到端 API 检查。
 * - 这些测试应断言操作者可见行为，而不是私有实现细节。
 */

import {
  expect,
  readJsonFixture,
} from "../helpers/runtime_testkit.mjs";

export function registerTests(register) {
  register({
    id: "A12",
    suite: "api",
    title: "Health endpoint exposes runtime mode, database state, migration version, and request id",
    required: true,
    async run({ harness }) {
      const server = await harness.startPostgresServer("api_health_test");
      const health = await server.request("/health");
      expect(health.ok, "postgres_health_failed");
      expect(health.data.runtimeMode === "postgres", "health_runtime_mode_mismatch");
      expect(health.data.requestId, "health_request_id_missing");
      expect(health.data.storeHealth?.database?.engine === "postgres", "health_database_engine_missing");
      expect(health.data.storeHealth?.migrationVersion, "health_migration_version_missing");
      return {
        requestId: health.data.requestId,
        database: health.data.storeHealth.database.databaseName,
      };
    },
  });

  register({
    id: "API-E2E",
    suite: "api",
    title: "Real postgres API flow can import, approve, publish, and pass consistency checks",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("math", "minimal_bundle.json");
      const server = await harness.startPostgresServer("api_flow_test");
      const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "api_suite",
          bundle: {
            ...bundle,
            bundle_id: `${bundle.bundle_id}_api`,
            lesson_id: `${bundle.lesson_id}_api`,
          },
        },
      });
      expect(imported.ok, `api_import_failed:${JSON.stringify(imported.data)}`);
      const approved = await server.request(
        `/api/runtime/review-tasks/${imported.data.result.reviewTaskId}/approve`,
        {
          method: "POST",
          body: {
            actor: "api_reviewer",
          },
        }
      );
      expect(approved.ok, `api_approve_failed:${JSON.stringify(approved.data)}`);
      const published = await server.request(
        `/api/runtime/lessons/${bundle.lesson_id}_api/publish`,
        {
          method: "POST",
          body: {
            actor: "api_publisher",
            lessonRevisionId: imported.data.result.lessonRevisionId,
          },
        }
      );
      expect(published.ok, `api_publish_failed:${JSON.stringify(published.data)}`);
      const consistency = await server.request("/api/runtime/internal/consistency");
      expect(consistency.ok, "consistency_endpoint_failed");
      expect(consistency.data.detail.ok === true, "consistency_report_not_ok");
      return {
        publicationId: published.data.result.publication.publication_id,
        consistencyStatus: consistency.data.detail.status,
      };
    },
  });

  register({
    id: "L10",
    suite: "api",
    title: "Invalid Content-Type is rejected with 415",
    required: true,
    async run({ harness }) {
      const server = await harness.startPostgresServer("api_content_type_test");
      const response = await server.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        json: false,
        body: "not-json",
        headers: {
          "Content-Type": "text/plain",
        },
      });
      expect(response.status === 415, `invalid_content_type_status_mismatch:${response.status}`);
      return {
        status: response.status,
        error: response.data?.error,
      };
    },
  });

  register({
    id: "L01-L17",
    suite: "api",
    title: "Admin POSTs require a token and error responses still include request ids",
    required: true,
    async run({ harness }) {
      const server = await harness.startPostgresServer("api_token_test");
      const response = await server.request("/api/runtime/bootstrap", {
        method: "POST",
        body: {},
        noAdminToken: true,
      });
      expect(response.status === 401, `missing_admin_token_status_mismatch:${response.status}`);
      expect(response.headers["x-request-id"], "missing_request_id_header_on_error");
      return {
        status: response.status,
        requestId: response.headers["x-request-id"],
      };
    },
  });
}
