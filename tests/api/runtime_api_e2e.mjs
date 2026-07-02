/**
 * 用途：
 * - 注册针对运行时主干 HTTP 服务的端到端 API 检查。
 * - 这些测试应断言操作者可见行为，而不是私有实现细节。
 */

import fs from "node:fs/promises";
import path from "node:path";
import {
  expect,
  readJsonFixture,
  runProcess,
  workspaceRoot,
} from "../helpers/runtime_testkit.mjs";
import { resolveBundledPythonPath } from "../../tools/runtime_dependency_paths.mjs";

function buildInvalidVisualExportPayload() {
  return {
    lesson: {
      lesson_id: "visual_export_preflight_lesson",
      lesson_title: "Visual Export Preflight",
      stage: "senior",
      grade: "g11",
      season: "autumn",
      lesson_no: 1,
      source_pdf_name: "visual_export_preflight.pdf",
      knowledge_point_count: 1,
      objectives: "Preflight validation",
    },
    splitLesson: {
      lesson_id: "visual_export_preflight_lesson",
      question_count: 1,
      tree: [
        {
          module: "Visual Export",
          items: ["Root"],
        },
      ],
      auditSummary: {
        reviewedCount: 1,
        pendingCount: 0,
      },
      questions: [
        {
          id: "visual_export_question_1",
          localTaskId: "V-001",
          checkpoint: "阅读理解主旨大意",
          componentLabel: "single_choice",
          sourcePage: 1,
          question_visual_structure: {
            schema_version: "question_visual_structure.v1.1",
            generated_by: "api_test",
            runtime_run_id: "run_api_preflight",
            question_uid: "visual_export_p001_q001",
            stem_md: "Choose the matching diagram.",
            answer_md: "A",
            analysis_md: "Option A matches the prompt.",
            legacy_stem_md:
              "Choose the matching diagram.\n\nA. ![qa_visual_export_p001_q001_option_A_001](asset://qa_visual_export_p001_q001_option_A_001)",
            options: [
              {
                option_key: "A",
                asset_ids: ["qa_visual_export_p001_q001_option_A_001"],
              },
            ],
            content_blocks: [
              {
                block_type: "option_image",
                option_key: "A",
                asset_id: "qa_visual_export_p001_q001_option_A_001",
              },
            ],
            visual_assets: [
              {
                asset_id: "qa_visual_export_p001_q001_option_A_001",
                display_ref: "asset://qa_visual_export_p001_q001_option_A_001",
                storage_key:
                  "question_assets/visual_export_p001_q001/run_api_preflight/options/A/001.png",
                bbox_space: "option_crop",
                source_image_asset_id:
                  "qa_visual_export_p001_q001_option_A_001_source",
                placement_scope: "option_inline",
                option_key: "A",
                attach_status: "attached",
                file_status: "failed",
              },
            ],
            review_flags: [],
          },
        },
      ],
    },
    reviewQueue: [],
    selectedVersions: ["基础版"],
    selectedAudiences: ["教师版"],
    selectedFormats: ["DOCX"],
    includeCompass: false,
  };
}

function buildValidVisualExportPayload(assetBaseDir) {
  return {
    lesson: {
      lesson_id: "visual_export_asset_lesson",
      lesson_title: "Visual Export Asset Resolution",
      stage: "senior",
      grade: "g11",
      season: "autumn",
      lesson_no: 2,
      source_pdf_name: "visual_export_asset.pdf",
      knowledge_point_count: 1,
      objectives: "Export visual assets through storage_key",
    },
    splitLesson: {
      lesson_id: "visual_export_asset_lesson",
      assetBaseDir,
      question_count: 1,
      tree: [
        {
          module: "Visual Export",
          items: ["Asset Resolution"],
        },
      ],
      auditSummary: {
        reviewedCount: 1,
        pendingCount: 0,
      },
      questions: [
        {
          id: "visual_export_asset_question_1",
          localTaskId: "V-002",
          localNumber: "1",
          versionTags: ["基础版"],
          checkpoint: "阅读理解主旨大意",
          componentLabel: "single_choice",
          sourcePage: 2,
          question_visual_structure: {
            schema_version: "question_visual_structure.v1.1",
            generated_by: "api_test",
            runtime_run_id: "run_api_export_asset",
            question_uid: "visual_export_asset_p002_q001",
            stem_md: "Choose the matching picture.",
            answer_md: "A",
            analysis_md: "Option A matches the visual cue.",
            legacy_stem_md:
              "Choose the matching picture.\n\nA. ![qa_visual_export_asset_p002_q001_option_A_001](asset://qa_visual_export_asset_p002_q001_option_A_001)",
            options: [
              {
                option_key: "A",
                asset_ids: ["qa_visual_export_asset_p002_q001_option_A_001"],
              },
            ],
            content_blocks: [
              {
                block_id: "blk_stem_001",
                block_order: 1,
                scope: "stem",
                block_type: "markdown",
                text_md: "Choose the matching picture.",
              },
              {
                block_id: "blk_opt_A_text_001",
                block_order: 2,
                scope: "option",
                option_key: "A",
                block_type: "markdown",
                text_md: "A.",
              },
              {
                block_id: "blk_opt_A_img_001",
                block_order: 3,
                scope: "option",
                option_key: "A",
                block_type: "image",
                asset_id: "qa_visual_export_asset_p002_q001_option_A_001",
                display_ref: "asset://qa_visual_export_asset_p002_q001_option_A_001",
                storage_key:
                  "question_assets/visual_export_asset_p002_q001/run_api_export_asset/options/A/001.png",
              },
            ],
            visual_assets: [
              {
                asset_id: "qa_visual_export_asset_p002_q001_option_A_001",
                display_ref: "asset://qa_visual_export_asset_p002_q001_option_A_001",
                storage_key:
                  "question_assets/visual_export_asset_p002_q001/run_api_export_asset/options/A/001.png",
                bbox_space: "option_crop",
                source_image_asset_id:
                  "qa_visual_export_asset_p002_q001_option_A_001_source",
                placement_scope: "option_inline",
                option_key: "A",
                attach_status: "attached",
                file_status: "materialized",
              },
            ],
            review_flags: [],
          },
        },
      ],
    },
    reviewQueue: [],
    selectedVersions: ["基础版"],
    selectedAudiences: ["教师版"],
    selectedFormats: ["DOCX"],
    includeCompass: false,
  };
}

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

  register({
    id: "API-VIS-PREFLIGHT",
    suite: "api",
    title: "Export preflight rejects broken asset:// references before the legacy renderer runs",
    required: true,
    async run({ harness }) {
      const server = await harness.startPostgresServer("api_visual_preflight_test");
      const response = await server.request("/api/export/generate", {
        method: "POST",
        body: buildInvalidVisualExportPayload(),
      });
      expect(
        response.status === 400,
        `visual_export_preflight_status_mismatch:${response.status}`
      );
      expect(
        String(response.data?.error || "").startsWith("invalid_export_preflight:"),
        `visual_export_preflight_error_missing:${JSON.stringify(response.data)}`
      );
      return {
        status: response.status,
        error: response.data?.error,
      };
    },
  });

  register({
    id: "API-VIS-EXPORT",
    suite: "api",
    title: "Export can resolve question_visual_structure assets into DOCX media without cropPath",
    required: true,
    async run({ harness }) {
      const pythonExe = resolveBundledPythonPath() || process.env.PYTHON || "python";
      const assetBaseDir = path.join(harness.outputDir, "visual_export_assets");
      const assetRelativePath = path.join(
        "question_assets",
        "visual_export_asset_p002_q001",
        "run_api_export_asset",
        "options",
        "A",
        "001.png"
      );
      const assetPath = path.join(assetBaseDir, assetRelativePath);
      await fs.mkdir(path.dirname(assetPath), { recursive: true });
      const createImageScript = `
import sys
from pathlib import Path
sys.path.insert(0, str(Path(r"${workspaceRoot.replace(/\\/g, "\\\\")}") / "tools" / "vendor"))
from PIL import Image
target = Path(r"${assetPath.replace(/\\/g, "\\\\")}")
target.parent.mkdir(parents=True, exist_ok=True)
Image.new("RGB", (24, 24), (40, 120, 220)).save(target)
`;
      const createImage = await runProcess(pythonExe, ["-c", createImageScript]);
      expect(createImage.code === 0, `visual_export_asset_create_failed:${createImage.stderr || createImage.stdout}`);

      const server = await harness.startPostgresServer("api_visual_export_asset_test");
      const bundle = await readJsonFixture("english", "minimal_bundle.json");
      const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "api_visual_export_suite",
          bundle: {
            ...bundle,
            bundle_id: `${bundle.bundle_id}_visual_export_asset`,
            lesson_id: "visual_export_asset_lesson",
          },
        },
      });
      expect(imported.ok, `visual_export_seed_import_failed:${JSON.stringify(imported.data)}`);
      const approved = await server.request(
        `/api/runtime/review-tasks/${imported.data.result.reviewTaskId}/approve`,
        {
          method: "POST",
          body: {
            actor: "api_visual_export_reviewer",
          },
        }
      );
      expect(approved.ok, `visual_export_seed_approve_failed:${JSON.stringify(approved.data)}`);
      const published = await server.request("/api/runtime/lessons/visual_export_asset_lesson/publish", {
        method: "POST",
        body: {
          actor: "api_visual_export_publisher",
          lessonRevisionId: imported.data.result.lessonRevisionId,
        },
      });
      expect(published.ok, `visual_export_seed_publish_failed:${JSON.stringify(published.data)}`);

      const response = await server.request("/api/export/generate", {
        method: "POST",
        body: buildValidVisualExportPayload(assetBaseDir),
      });
      expect(response.ok, `visual_export_should_succeed:${JSON.stringify(response.data)}`);
      expect(
        response.data?.item?.preflight?.checkedQuestionCount === 1,
        `visual_export_preflight_count_mismatch:${JSON.stringify(response.data?.item?.preflight)}`
      );
      const docxFile = response.data?.item?.files?.find((file) => file.format === "DOCX");
      expect(docxFile?.relativePath, `visual_export_docx_missing:${JSON.stringify(response.data?.item?.files)}`);

      const docxPath = path.join(workspaceRoot, docxFile.relativePath);
      const inspectScript = `
import json
import zipfile
from pathlib import Path
docx_path = Path(r"${docxPath.replace(/\\/g, "\\\\")}")
with zipfile.ZipFile(docx_path) as archive:
    media_entries = [name for name in archive.namelist() if name.startswith("word/media/")]
print(json.dumps({"media_count": len(media_entries), "entries": media_entries}))
`;
      const inspect = await runProcess(pythonExe, ["-c", inspectScript]);
      expect(inspect.code === 0, `visual_export_docx_inspect_failed:${inspect.stderr || inspect.stdout}`);
      const parsed = JSON.parse(inspect.stdout.trim());
      expect(parsed.media_count >= 1, `visual_export_docx_media_missing:${inspect.stdout}`);
      return {
        docx: docxFile.relativePath,
        mediaCount: parsed.media_count,
      };
    },
  });
}
