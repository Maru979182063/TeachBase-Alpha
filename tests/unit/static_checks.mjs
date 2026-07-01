/**
 * 用途：
 * - 运行不依赖外部服务的静态仓库检查。
 * - 这个文件用于在重型套件启动前低成本捕获回归。
 */

import path from "node:path";
import fs from "node:fs/promises";
import {
  expect,
  listFiles,
  runProcess,
  workspaceRoot,
} from "../helpers/runtime_testkit.mjs";
import { resolveBundledPythonPath } from "../../tools/runtime_dependency_paths.mjs";

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

  register({
    id: "A09",
    suite: "static",
    title: "8790 stays on the store interface and 8792 is only a deprecated forwarding shim",
    required: true,
    async run() {
      const runtimeSource = await fs.readFile(
        path.join(workspaceRoot, "tools", "mock_workbench_api_server.mjs"),
        "utf8"
      );
      const compatSource = await fs.readFile(
        path.join(workspaceRoot, "tools", "runtime_backbone_api_server.mjs"),
        "utf8"
      );
      const startScript = await fs.readFile(
        path.join(workspaceRoot, "tools", "start_runtime_backbone_demo.ps1"),
        "utf8"
      );

      expect(
        runtimeSource.includes("createRuntimeBackboneStore"),
        "runtime_api_should_use_store_interface"
      );
      expect(
        !runtimeSource.includes("loadState(") && !runtimeSource.includes("saveState("),
        "runtime_api_should_not_call_legacy_file_state_directly"
      );
      expect(
        compatSource.includes("RUNTIME_BACKBONE_COMPAT_TARGET") &&
          compatSource.includes("X-Runtime-Deprecated"),
        "compat_server_should_forward_to_8790"
      );
      expect(
        !compatSource.includes("loadState(") && !compatSource.includes("saveState("),
        "compat_server_should_not_touch_state_store"
      );
      expect(
        startScript.includes("start_mock_workbench_runtime.ps1") &&
          startScript.includes("8790"),
        "legacy_start_script_should_delegate_to_8790"
      );
      return {
        officialPort: 8790,
        deprecatedPort: 8792,
      };
    },
  });

  register({
    id: "A10",
    suite: "static",
    title: "Core runtime and demo scripts do not hardcode one local workspace path",
    required: true,
    async run() {
      const targets = [
        path.join(workspaceRoot, "tools", "build_mock_workbench_data.mjs"),
        path.join(workspaceRoot, "tools", "start_demo_stack.ps1"),
        path.join(workspaceRoot, "tools", "start_mock_workbench_runtime.ps1"),
        path.join(workspaceRoot, "config", "runtime_observability.yaml"),
      ];
      const forbidden = ["C:/Users/EDY/Documents/教研基建", "C:\\Users\\EDY\\Documents\\教研基建"];
      const hits = [];
      for (const filePath of targets) {
        const source = await fs.readFile(filePath, "utf8");
        for (const pattern of forbidden) {
          if (source.includes(pattern)) {
            hits.push({
              file: path.relative(workspaceRoot, filePath),
              pattern,
            });
          }
        }
      }
      expect(hits.length === 0, `hardcoded_local_workspace_path_hits:${JSON.stringify(hits)}`);
      return {
        checkedFiles: targets.length,
      };
    },
  });

  register({
    id: "A11",
    suite: "static",
    title: "Docs keep the production policy gate honest and describe the LessonDraftBundle boundary",
    required: true,
    async run() {
      const policyDocs = [
        path.join(workspaceRoot, "docs", "production_readiness_audit.md"),
        path.join(workspaceRoot, "docs", "production_readiness_defects.md"),
        path.join(workspaceRoot, "docs", "production_readiness_final_report.md"),
        path.join(workspaceRoot, "docs", "three_track_known_limitations.md"),
      ];
      const bundleDocs = [
        path.join(workspaceRoot, "docs", "README.md"),
        path.join(workspaceRoot, "docs", "three_track_validation_baseline_report.md"),
        path.join(workspaceRoot, "docs", "three_track_validation_release_notes.md"),
        path.join(workspaceRoot, "docs", "three_track_known_limitations.md"),
      ];

      for (const filePath of policyDocs) {
        const source = await fs.readFile(filePath, "utf8");
        expect(source.includes("POLICY-001"), `policy_gate_marker_missing:${path.basename(filePath)}`);
        expect(!source.includes("ARCH-002"), `legacy_arch002_reference_still_present:${path.basename(filePath)}`);
      }

      for (const filePath of bundleDocs) {
        const source = await fs.readFile(filePath, "utf8");
        expect(source.includes("LessonDraftBundle"), `bundle_boundary_marker_missing:${path.basename(filePath)}`);
      }

      return {
        policyDocs: policyDocs.length,
        bundleDocs: bundleDocs.length,
      };
    },
  });

  register({
    id: "A13",
    suite: "static",
    title: "Visual Python helpers emit versioned storage keys and carry runtime_run_id into question_visual_structure",
    required: true,
    async run() {
      const pythonExe = resolveBundledPythonPath() || process.env.PYTHON || "python";
      const script = `
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(r"${workspaceRoot.replace(/\\/g, "\\\\")}") / "tools"))
from option_crop_staging import _make_asset
from visual_transcription_core import build_question_visual_structure

asset = _make_asset(
    question_uid="visual_doc_p003_q001",
    runtime_run_id="run_visual_contract_001",
    role="option",
    ordinal=1,
    bbox_space="question_image",
    bbox_json={"x": 1, "y": 2, "w": 3, "h": 4},
    image_width=100,
    image_height=80,
    source_image_role="question_image",
    option_key="A",
    candidate_option_key="A",
    confidence=0.95,
    attach_status="attached",
    placement_scope="option_inline",
    review_flags=[],
    detector_source="contract_test",
)
qvs = build_question_visual_structure(
    {
        "question_uid": "visual_doc_p003_q001",
        "runtime_run_id": "run_visual_contract_001",
        "staged_visual_assets": [asset],
        "option_visual_blocks": [],
        "option_detection_review_flags": [],
        "gating_result": {},
    },
    {
        "question_id": "visual_q1",
        "stem_text_md": "A. option",
        "answer_text_md": "A",
        "analysis_text_md": "analysis",
    },
)
print(json.dumps({
    "storage_key": asset["storage_key"],
    "asset_runtime_run_id": asset["runtime_run_id"],
    "qvs_runtime_run_id": qvs["runtime_run_id"],
}, ensure_ascii=False))
`;
      const result = await runProcess(pythonExe, ["-c", script]);
      expect(result.code === 0, `visual_python_contract_failed:${result.stderr || result.stdout}`);
      const parsed = JSON.parse(result.stdout.trim());
      expect(
        parsed.storage_key ===
          "question_assets/visual_doc_p003_q001/run_visual_contract_001/options/A/001.png",
        `visual_storage_key_strategy_mismatch:${parsed.storage_key}`
      );
      expect(
        parsed.asset_runtime_run_id === "run_visual_contract_001",
        `visual_asset_runtime_run_id_missing:${parsed.asset_runtime_run_id}`
      );
      expect(
        parsed.qvs_runtime_run_id === "run_visual_contract_001",
        `visual_qvs_runtime_run_id_missing:${parsed.qvs_runtime_run_id}`
      );
      return parsed;
    },
  });
}
