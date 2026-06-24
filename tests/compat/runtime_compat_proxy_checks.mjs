/**
 * Purpose:
 * - verify the deprecated 8792 layer is only a transport proxy to 8790
 * - prove auth, rate limiting, and request bodies are still enforced upstream
 */

import {
  expect,
  readJsonFixture,
} from "../helpers/runtime_testkit.mjs";

export function registerTests(register) {
  register({
    id: "COMPAT-01",
    suite: "compat",
    title: "8792 preserves auth, role checks, request bodies, status codes, and deprecation headers",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("math", "minimal_bundle.json");
      const official = await harness.startPostgresServer("compat_proxy_test");
      const compat = await harness.startCompatServer({
        targetPort: Number(new URL(official.baseUrl).port),
      });

      const unauthorized = await compat.request("/api/runtime/bootstrap", {
        method: "POST",
        body: {},
      });
      expect(unauthorized.status === 401, `compat_unauthorized_status:${unauthorized.status}`);
      expect(unauthorized.headers["x-runtime-deprecated"] === "true", "compat_deprecated_header_missing");

      const imported = await compat.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        headers: {
          "X-Runtime-Admin-Token": official.adminToken,
        },
        body: {
          actor: "compat_importer",
          bundle: {
            ...bundle,
            lesson_id: `${bundle.lesson_id}_compat`,
            bundle_id: `${bundle.bundle_id}_compat`,
          },
        },
      });
      expect(imported.ok, `compat_import_failed:${JSON.stringify(imported.data)}`);
      expect(imported.data.result.lessonRevisionId, "compat_request_body_should_reach_8790");

      const forbiddenPublish = await compat.request(
        `/api/runtime/lessons/${bundle.lesson_id}_compat/publish`,
        {
          method: "POST",
          headers: {
            "X-Runtime-Admin-Token": official.adminToken,
          },
          body: {
            actor: "ordinary_user",
            lessonRevisionId: imported.data.result.lessonRevisionId,
          },
        }
      );
      expect(forbiddenPublish.status === 403, `compat_role_status:${forbiddenPublish.status}`);

      const invalidContentType = await compat.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        json: false,
        headers: {
          "Content-Type": "text/plain",
          "X-Runtime-Admin-Token": official.adminToken,
        },
        body: "not-json",
      });
      expect(invalidContentType.status === 415, `compat_invalid_content_type_status:${invalidContentType.status}`);

      return {
        importedLessonRevisionId: imported.data.result.lessonRevisionId,
        unauthorizedStatus: unauthorized.status,
        forbiddenStatus: forbiddenPublish.status,
        invalidContentTypeStatus: invalidContentType.status,
      };
    },
  });

  register({
    id: "COMPAT-02",
    suite: "compat",
    title: "8792 requests still inherit upstream rate limiting",
    required: true,
    async run({ harness }) {
      const official = await harness.startPostgresServer({
        prefix: "compat_rate_limit_test",
        // Tighten the window for this suite so the inherited 429 behavior is deterministic.
        env: {
          RUNTIME_RATE_LIMIT_WINDOW_MS: "60000",
          RUNTIME_RATE_LIMIT_MAX_REQUESTS: "3",
        },
      });
      const compat = await harness.startCompatServer({
        targetPort: Number(new URL(official.baseUrl).port),
      });

      const responses = [];
      for (let index = 0; index < 12; index += 1) {
        responses.push(
          await compat.request("/api/runtime/bootstrap", {
            method: "POST",
            headers: {
              "X-Runtime-Admin-Token": official.adminToken,
            },
            body: {},
          })
        );
      }
      const limited = responses.filter((item) => item.status === 429).length;
      expect(limited >= 1, "compat_requests_should_be_rate_limited");
      return {
        limited,
        total: responses.length,
      };
    },
  });

  register({
    id: "COMPAT-03",
    suite: "compat",
    title: "8792 returns a clear upstream-unavailable response when 8790 is down",
    required: true,
    async run({ harness }) {
      const compat = await harness.startCompatServer({
        targetPort: 65501,
        allowUnavailableHealth: true,
      });
      const response = await compat.request("/health");
      expect(response.status === 503, `compat_upstream_unavailable_status:${response.status}`);
      expect(
        response.data?.error === "runtime_backbone_compat_target_unavailable",
        "compat_upstream_unavailable_error_missing"
      );
      return {
        status: response.status,
      };
    },
  });

  register({
    id: "COMPAT-04",
    suite: "compat",
    title: "8792 can be fully disabled by environment flag",
    required: true,
    async run({ harness }) {
      const compat = await harness.startCompatServer({
        targetPort: 8790,
        env: {
          RUNTIME_BACKBONE_COMPAT_ENABLED: "false",
        },
      });

      let failed = false;
      try {
        await compat.request("/health");
      } catch {
        failed = true;
      }
      expect(failed, "compat_port_should_not_listen_when_disabled");
      return {
        disabled: true,
      };
    },
  });
}
