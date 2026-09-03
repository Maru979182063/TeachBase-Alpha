import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const workspaceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const reportPath = path.join(workspaceRoot, "docs", "reports", "editor_backend_contract_audit_20260831.json");

function prototypeRootFromArgs() {
  const index = process.argv.indexOf("--prototype-root");
  const value = index >= 0 ? process.argv[index + 1] : process.env.TEACHBASE_PROTOTYPE_ROOT;
  if (!value) throw new Error("prototype_root_required");
  return path.resolve(value);
}

function has(source, expression) {
  return expression.test(source);
}

function entityCount(fixture, name) {
  return Array.isArray(fixture[name]) ? fixture[name].length : 0;
}

async function main() {
  const prototypeRoot = prototypeRootFromArgs();
  const editorPath = path.join(prototypeRoot, "editor-lab.js");
  const fixturePath = path.join(prototypeRoot, "fixtures", "alpha-build-fixtures.json");
  const [editorSource, fixtureText] = await Promise.all([
    fs.readFile(editorPath, "utf8"),
    fs.readFile(fixturePath, "utf8"),
  ]);
  const fixture = JSON.parse(fixtureText);

  const observedContracts = [
    ["formula_latex_and_mathml", /name:\s*["']inlineMath["'][\s\S]*?latex:[\s\S]*?mathml:/],
    ["formula_inline_and_block_modes", /name:\s*["']blockMath["']/],
    ["mind_map_tree", /name:\s*["']mindMap["'][\s\S]*?nodes:/],
    ["mind_map_student_blank_nodes", /studentBlankNodeIds/],
    ["text_student_blank_mark", /name:\s*["']studentBlank["']/],
    ["knowledge_student_blank_ranges", /studentBlankRanges/],
    ["master_plus_three_overrides", /master-overrides-v1[\s\S]*?versionOverrides/],
    ["teacher_and_student_preview", /previewAudience\s*===\s*["']student["']/],
    ["immutable_export_snapshot_intent", /handout_export_snapshots_v1/],
    ["question_revision_pins", /questionId[\s\S]*?revisionId/],
    ["knowledge_revision_pins", /knowledgeId[\s\S]*?revisionId/],
  ].map(([name, expression]) => ({ name, observed: has(editorSource, expression) }));

  const risks = [
    { code: "browser_local_storage_is_source_of_truth", observed: has(editorSource, /localStorage\.setItem\(STORAGE_KEY/) },
    { code: "client_generated_time_random_ids", observed: has(editorSource, /Date\.now\(\)[\s\S]*?Math\.random\(\)/) },
    { code: "handwritten_markdown_parser", observed: has(editorSource, /function markdownToHtml/) },
    { code: "formula_render_errors_suppressed", observed: has(editorSource, /throwOnError:\s*false/) },
    { code: "base64_image_drafts", observed: has(editorSource, /readAsDataURL/) },
    { code: "markdown_and_html_dual_authority", observed: has(editorSource, /overrideStemMarkdown/) && has(editorSource, /overrideStemHtml/) },
    { code: "editor_payload_has_no_schema_version", observed: !has(editorSource, /editorModel:\s*["']master-overrides-v1["'][\s\S]{0,300}schemaVersion/) },
    { code: "no_optimistic_concurrency_contract", observed: !has(editorSource, /expectedRevision|ifMatch|etag/i) },
  ];

  const report = {
    reportVersion: "editor-backend-contract-audit-v1",
    generatedAt: new Date().toISOString(),
    source: {
      logicalName: "workbench-demo-current-prototype",
      inputContract: "TEACHBASE_PROTOTYPE_ROOT or --prototype-root",
      storedAbsolutePath: false,
      files: [
        { path: "editor-lab.js", sha256: crypto.createHash("sha256").update(editorSource).digest("hex") },
        { path: "fixtures/alpha-build-fixtures.json", sha256: crypto.createHash("sha256").update(fixtureText).digest("hex") },
      ],
    },
    fixtureEvidence: {
      handoutDrafts: entityCount(fixture, "handoutDrafts"),
      previewConfirmations: entityCount(fixture, "previewConfirmations"),
      handoutSnapshots: entityCount(fixture, "handoutSnapshots"),
      exportRequests: entityCount(fixture, "exportRequests"),
      exportFiles: entityCount(fixture, "exportFiles"),
      exportJobs: entityCount(fixture, "exportJobs"),
    },
    observedContracts,
    risks,
    ownership: {
      frontend: ["selection_and_cursor", "drag_and_layout", "instant_formula_preview", "instant_mind_map_preview", "blank_selection_ui"],
      backend: ["structured_source", "schema_validation", "revision_history", "optimistic_concurrency", "permissions", "immutable_snapshots", "markdown_formula_normalization", "deterministic_export", "artifact_archive"],
    },
    backendDecisions: [
      "Tiptap JSON remains the canonical editor source; generated HTML, SVG, canvas output, and screenshots are projections only.",
      "Formula nodes persist LaTeX and optional MathML, never KaTeX HTML as source of truth.",
      "Mind maps persist stable node IDs, tree structure, layout intent, and student blank node IDs.",
      "Student blanks are versioned content annotations and must be included in immutable snapshots.",
      "Markdown and LaTeX are validated and normalized by the backend before snapshot confirmation and export.",
      "DOCX and PDF are generated from immutable snapshots and registered as file versions.",
    ],
  };

  await fs.mkdir(path.dirname(reportPath), { recursive: true });
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify({
    ok: observedContracts.every((item) => item.observed),
    observedContractCount: observedContracts.filter((item) => item.observed).length,
    riskCount: risks.filter((item) => item.observed).length,
    report: path.relative(workspaceRoot, reportPath).replaceAll("\\", "/"),
  }, null, 2)}\n`);
}

await main();
