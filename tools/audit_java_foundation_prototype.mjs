import fs from "node:fs/promises";
import path from "node:path";

import { workspaceRoot } from "../tests/helpers/runtime_testkit.mjs";

const REPORT_DATE = "20260831";
const reportDirectory = path.join(workspaceRoot, "docs", "reports");
const jsonPath = path.join(reportDirectory, `java_foundation_prototype_inventory_${REPORT_DATE}.json`);
const markdownPath = path.join(reportDirectory, `java_foundation_prototype_inventory_${REPORT_DATE}.md`);

function parseArguments(argv) {
  const index = argv.indexOf("--prototype-root");
  const value = index >= 0 ? argv[index + 1] : process.env.TEACHBASE_PROTOTYPE_ROOT;
  if (!value) {
    throw new Error("prototype_root_required:set_TEACHBASE_PROTOTYPE_ROOT_or_use_--prototype-root");
  }
  return path.resolve(value);
}

function objectKeys(values) {
  return [...new Set(values.flatMap((value) => value && typeof value === "object" ? Object.keys(value) : []))].sort();
}

function collectStringValues(value, output = []) {
  if (typeof value === "string") {
    output.push(value);
    return output;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectStringValues(item, output);
    return output;
  }
  if (value && typeof value === "object") {
    for (const item of Object.values(value)) collectStringValues(item, output);
  }
  return output;
}

function collectAbsolutePathLocations(value, pointer = "$", output = []) {
  if (typeof value === "string") {
    if (/^[A-Za-z]:[\\/]/.test(value)) output.push(pointer);
    return output;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => collectAbsolutePathLocations(item, `${pointer}[${index}]`, output));
    return output;
  }
  if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      collectAbsolutePathLocations(item, `${pointer}.${key}`, output);
    }
  }
  return output;
}

function matches(source, expression) {
  return expression.test(source);
}

function sortedMatches(source, expression) {
  return [...new Set([...source.matchAll(expression)].map((match) => match[1]))].sort();
}

async function listFiles(root, relative = "") {
  const current = path.join(root, relative);
  const entries = await fs.readdir(current, { withFileTypes: true });
  const result = [];
  for (const entry of entries) {
    const child = path.join(relative, entry.name);
    if (entry.isDirectory()) result.push(...await listFiles(root, child));
    else result.push(child.replaceAll("\\", "/"));
  }
  return result;
}

function renderMarkdown(report) {
  const lines = [
    "# Java Foundation Prototype Contract Inventory",
    "",
    `- Prototype schema: \`${report.prototype.schemaVersion}\``,
    `- Effective questions: **${report.prototype.effectiveQuestionCount}**`,
    `- Handout drafts: **${report.prototype.handoutDraftCount}**`,
    `- Handout snapshots: **${report.prototype.handoutSnapshotCount}**`,
    `- Editor model: \`${report.editor.model}\``,
    `- Prototype tests discovered: **${report.tests.files.length}**`,
    "",
    "The source directory is supplied at execution time. No machine-specific absolute path is stored in this report.",
    "",
    "## Entity Contracts",
    "",
    "| Fixture entity | Records | Fields |",
    "|---|---:|---|",
    ...report.entities.map((entity) => `| \`${entity.name}\` | ${entity.count} | ${entity.fields.map((field) => `\`${field}\``).join(", ")} |`),
    "",
    "## Editor Persistence",
    "",
    ...report.editor.capabilities.map((capability) => `- ${capability.supported ? "PASS" : "MISSING"}: ${capability.name}`),
    "",
    `Question reference override fields: ${report.editor.questionOverrideFields.map((field) => `\`${field}\``).join(", ")}`,
    "",
    "## Backend Implications",
    "",
    ...report.backendImplications.map((item) => `- ${item}`),
    "",
    "## Limitations",
    "",
    ...report.limitations.map((item) => `- ${item}`),
    "",
  ];
  return `${lines.join("\n")}\n`;
}

async function main() {
  const prototypeRoot = parseArguments(process.argv.slice(2));
  const fixturePath = path.join(prototypeRoot, "fixtures", "alpha-build-fixtures.json");
  const editorPath = path.join(prototypeRoot, "editor-lab.js");
  const alphaStatePath = path.join(prototypeRoot, "alpha-page-data.js");
  const referenceRepositoryPath = path.join(prototypeRoot, "editor-reference-repository.js");
  const questionDomainPath = path.join(prototypeRoot, "question-domain.js");

  const [fixtureText, editorSource, alphaStateSource, referenceSource, questionDomainSource, files] = await Promise.all([
    fs.readFile(fixturePath, "utf8"),
    fs.readFile(editorPath, "utf8"),
    fs.readFile(alphaStatePath, "utf8"),
    fs.readFile(referenceRepositoryPath, "utf8"),
    fs.readFile(questionDomainPath, "utf8"),
    listFiles(prototypeRoot),
  ]);
  const fixture = JSON.parse(fixtureText);
  const entityNames = [
    "baskets",
    "publishedBasketSnapshots",
    "normalizedHandouts",
    "handoutDrafts",
    "previewConfirmations",
    "handoutSnapshots",
    "exportRequests",
    "exportFiles",
    "exportJobs",
    "effectiveQuestions",
    "replacementCandidates",
  ];
  const entities = entityNames.map((name) => ({
    name,
    count: Array.isArray(fixture[name]) ? fixture[name].length : 0,
    fields: objectKeys(Array.isArray(fixture[name]) ? fixture[name] : []),
  }));
  const questions = fixture.effectiveQuestions || [];
  const provenanceFields = objectKeys(questions.map((question) => question.provenance));
  const assetFields = objectKeys(questions.map((question) => question.assets));
  const absolutePathValues = collectStringValues(fixture).filter((value) => /^[A-Za-z]:[\\/]/.test(value));
  const absolutePathLocations = collectAbsolutePathLocations(fixture);

  const capabilities = [
    { name: "Tiptap JSON is read from editor.getJSON()", supported: matches(editorSource, /editor\.getJSON\(\)/) },
    { name: "master plus per-version overrides are persisted", supported: matches(editorSource, /editorModel:\s*["']master-overrides-v1["']/) },
    { name: "question references pin questionId and revisionId", supported: matches(editorSource, /questionId/) && matches(editorSource, /revisionId/) },
    { name: "knowledge references pin knowledgeId and revisionId", supported: matches(editorSource, /knowledgeId/) && matches(editorSource, /knowledgeReference/) },
    { name: "safety snapshots exist", supported: matches(editorSource, /SAFETY_SNAPSHOT/) },
    { name: "export snapshots are immutable copies in the prototype flow", supported: matches(editorSource, /handout_export_snapshots_v1/) && matches(alphaStateSource, /frozenBlocks/) },
    { name: "preview confirmation is explicit before export", supported: matches(alphaStateSource, /confirmPreview/) && matches(alphaStateSource, /previewConfirmedByVersionId/) },
  ];

  const report = {
    reportVersion: "java-foundation-prototype-inventory-v1",
    generatedAt: new Date().toISOString(),
    source: {
      logicalName: "workbench-demo-local-prototype",
      inputContract: "TEACHBASE_PROTOTYPE_ROOT or --prototype-root",
      storedAbsolutePath: false,
      inspectedFiles: [
        "fixtures/alpha-build-fixtures.json",
        "alpha-page-data.js",
        "editor-lab.js",
        "editor-reference-repository.js",
        "question-domain.js",
      ],
    },
    prototype: {
      schemaVersion: fixture.schemaVersion || null,
      effectiveQuestionCount: questions.length,
      handoutDraftCount: fixture.handoutDrafts?.length || 0,
      handoutSnapshotCount: fixture.handoutSnapshots?.length || 0,
      exportJobCount: fixture.exportJobs?.length || 0,
      provisionalRuleCount: fixture.provisionalRules?.length || 0,
    },
    entities,
    questionContract: {
      fields: objectKeys(questions),
      provenanceFields,
      assetFields,
      hasParentChildQuestions: questions.some((question) => Array.isArray(question.children) && question.children.length > 0),
      hasStructuredContent: questions.some((question) => question.content && typeof question.content === "object"),
      hasDisplayBlocks: questions.some((question) => Array.isArray(question.displayBlocks) && question.displayBlocks.length > 0),
      hasRevisionPins: questions.some((question) => question.approvedVersion != null),
    },
    editor: {
      model: matches(editorSource, /editorModel:\s*["']master-overrides-v1["']/) ? "master-overrides-v1" : "unknown",
      canonicalFormat: matches(editorSource, /editor\.getJSON\(\)/) ? "tiptap-json" : "not-confirmed",
      referenceNodeTypes: ["questionReference", "knowledgeReference"].filter((type) => editorSource.includes(type)),
      questionOverrideFields: sortedMatches(editorSource, /\b(override[A-Z][A-Za-z0-9_]*)\b/g),
      capabilities,
    },
    repositoryAdapters: {
      editorReferenceRepositoryPresent: referenceSource.includes("revisionId"),
      questionDomainPresent: questionDomainSource.length > 0,
    },
    tests: {
      files: files.filter((file) => /^tests\/.+\.test\.mjs$/.test(file)).sort(),
    },
    portability: {
      absolutePathValueCount: absolutePathValues.length,
      passesNoAbsolutePathFixtureCheck: absolutePathValues.length === 0,
      absolutePathLocations,
    },
    backendImplications: [
      "Question identity and question revision must be separate because editor references pin both values.",
      "Human review must bind to a question revision; editing content creates an unreviewed revision.",
      "The handout model needs a master document, three version projections or overrides, drafts, immutable revisions, confirmations, and export snapshots.",
      "Question, knowledge, and file references need relational projections even when Tiptap JSON remains the canonical editor payload.",
      "Published snapshots must freeze question content and assets so later question edits do not mutate an exported handout.",
      "Source provenance needs structured file, page or block evidence; a display string alone is insufficient.",
    ],
    limitations: [
      "The prototype is a high-fidelity local application, not a committed backend API contract.",
      "Field presence demonstrates UI demand but does not establish database cardinality or authorization rules.",
      "The inventory does not treat page identifiers such as S01-S07 as backend module boundaries.",
    ],
  };

  await fs.mkdir(reportDirectory, { recursive: true });
  await fs.writeFile(jsonPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  await fs.writeFile(markdownPath, renderMarkdown(report), "utf8");
  process.stdout.write(`${JSON.stringify({ ok: capabilities.every((item) => item.supported), portableFixture: report.portability.passesNoAbsolutePathFixtureCheck, absolutePathDebtCount: report.portability.absolutePathValueCount, entityCount: entities.length, effectiveQuestionCount: report.prototype.effectiveQuestionCount, jsonPath: path.relative(workspaceRoot, jsonPath), markdownPath: path.relative(workspaceRoot, markdownPath) }, null, 2)}\n`);
  if (!capabilities.every((item) => item.supported)) process.exitCode = 1;
}

await main();
