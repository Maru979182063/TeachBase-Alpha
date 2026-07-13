import fs from "node:fs/promises";
import path from "node:path";

import {
  expect,
  runProcess,
  workspaceRoot,
} from "../helpers/runtime_testkit.mjs";
import { resolveBundledPythonPath } from "../../tools/runtime_dependency_paths.mjs";
import { ensureTinyPng } from "./release_gate_shared.mjs";

export function registerTests(register) {
  register({
    id: "RG-HTML-01",
    suite: "release_gate_html",
    title: "HTML externalization stays a review layer, keeps relative asset paths, and renders evidence_only separately",
    required: true,
    async run({ outputDir }) {
      const reviewDir = path.join(outputDir, "html_externalization");
      const htmlPath = path.join(reviewDir, "question_asset_review.html");
      await ensureTinyPng(
        reviewDir,
        "question_assets/html_fixture/run_html/options/A/001.png"
      );
      await ensureTinyPng(
        reviewDir,
        "question_assets/html_fixture/run_html/evidence/001.png"
      );

      const payload = {
        generated_at: "2026-07-01T00:00:00",
        question_count: 1,
        asset_count: 2,
        questions: [
          {
            question_id: "html_fixture_q1",
            component_label: "single_choice",
            local_number: "1",
            display_markdown: "Choose the matching image.",
            display_blocks: [
              {
                type: "markdown",
                field: "stem",
                content: "Choose the matching image.",
              },
              {
                type: "image",
                field: "stem",
                asset_id: "qa_html_option_A_001",
              },
            ],
            assets: [
              {
                asset_id: "qa_html_option_A_001",
                asset_role: "option",
                role: "option",
                placement: "option_inline",
                placement_scope: "option_inline",
                display_ref: "asset://qa_html_option_A_001",
                storage_key: "question_assets/html_fixture/run_html/options/A/001.png",
                external_label_kind: "option_key",
                external_label_text: "A",
                detector_source: "release_gate_html",
                bbox_audit: {
                  validity: "valid",
                },
              },
              {
                asset_id: "qa_html_evidence_001",
                asset_role: "evidence",
                role: "evidence",
                placement: "evidence_only",
                placement_scope: "evidence_only",
                display_ref: "asset://qa_html_evidence_001",
                storage_key: "question_assets/html_fixture/run_html/evidence/001.png",
                detector_source: "release_gate_html",
                bbox_audit: {
                  validity: "suspect",
                  suspect_reasons: ["option_anchor_missing"],
                },
              },
            ],
            missing_assets: [],
          },
        ],
      };

      const payloadPath = path.join(reviewDir, "payload.json");
      await fs.mkdir(reviewDir, { recursive: true });
      await fs.writeFile(payloadPath, JSON.stringify(payload, null, 2), "utf8");

      const pythonExe = resolveBundledPythonPath() || process.env.PYTHON || "python";
      const script = `
import copy
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(r"${workspaceRoot.replace(/\\/g, "\\\\")}") / "tools"))
from assetize_question_images import write_html_clean

payload_path = Path(r"${payloadPath.replace(/\\/g, "\\\\")}")
html_path = Path(r"${htmlPath.replace(/\\/g, "\\\\")}")
payload = json.loads(payload_path.read_text(encoding="utf-8"))
before = json.dumps(payload, ensure_ascii=False, sort_keys=True)
write_html_clean(html_path, payload)
after = json.dumps(payload, ensure_ascii=False, sort_keys=True)
print(json.dumps({"changed": before != after, "html_path": str(html_path)}, ensure_ascii=False))
`;
      const result = await runProcess(pythonExe, ["-c", script]);
      expect(result.code === 0, `html_externalization_python_failed:${result.stderr || result.stdout}`);
      const parsed = JSON.parse(result.stdout.trim());
      expect(parsed.changed === false, "html_externalization_should_not_mutate_payload");

      const html = await fs.readFile(htmlPath, "utf8");
      expect(
        html.includes("question_assets/html_fixture/run_html/options/A/001.png"),
        "html_should_use_relative_option_asset_path"
      );
      expect(
        html.includes("question_assets/html_fixture/run_html/evidence/001.png"),
        "html_should_render_evidence_asset"
      );
      expect(
        html.includes("asset://qa_html_evidence_001"),
        "html_should_surface_evidence_display_ref_for_review"
      );
      expect(
        !html.includes(workspaceRoot),
        "html_should_not_contain_absolute_workspace_path"
      );
      return {
        htmlPath,
      };
    },
  });
}
