import fs from "node:fs/promises";
import path from "node:path";

function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1]) throw new Error(`missing_argument:${name}`);
  return path.resolve(process.argv[index + 1]);
}

async function readJson(root, name) {
  return JSON.parse(await fs.readFile(path.join(root, name), "utf8"));
}

async function main() {
  const source = argument("--source");
  const output = argument("--output");
  const composition = await readJson(source, "composition.json");
  const capture = await readJson(source, "capture/capture-manifest.json");
  const student = await readJson(source, "student-differences.json");
  const blocks = (await fs.readFile(path.join(source, "content-index.jsonl"), "utf8"))
    .trim().split(/\r?\n/).map((line) => JSON.parse(line)).map((block) => ({
      blockId: block.blockId,
      sourceIndex: block.sourceIndex,
      kind: block.kind,
      xmlSha256: block.xmlSha256,
      imageCount: block.images.length,
    }));
  const deduplication = {
    policy: "golden_fixture_human_confirmed_content_equivalence",
    aliases: {
      "KQ-06": "K3-P02",
      "KQ-03": "CT-09",
      "HW-13": "KQ-02",
    },
  };
  const fixture = {
    schema: "teachbase.g4-handout-golden.v1",
    documentKey: composition.documentKey,
    title: "时态语态秘密武器",
    source: {
      logicalName: capture.source.logicalName,
      sha256: capture.source.sha256,
      contentBlockCount: capture.contentBlockCount,
      paragraphCount: capture.paragraphCount,
      tableCount: capture.tableCount,
      imageOccurrences: capture.imageOccurrences,
    },
    blocks,
    standardModules: composition.standardModules,
    questionSectionContainers: composition.questionSectionContainers,
    questions: composition.questions,
    topLevelSequence: composition.topLevelSequence,
    validation: composition.validation,
    deduplication,
    studentProjection: {
      canonicalEdition: student.canonicalEdition,
      storagePolicy: student.studentStoragePolicy,
      source: {
        logicalName: "时态语态秘密武器-学生版.docx",
        sha256: student.sources.student.sha256,
        contentBlockCount: student.sources.student.contentBlocks,
      },
      questionOccurrences: student.questionOccurrences,
      deltaTypes: student.deltaTypes,
      studentModuleRanges: student.studentModuleRanges,
    },
    artifactKeys: {
      originalDocx: "tests/fixtures/g4/english/teacher-original.docx",
      splitManifest: "tests/fixtures/g4/english/composition-manifest.json",
      preservationBundle: "tests/fixtures/g4/english/preservation-bundle.zip",
      roundtripOutput: "tests/fixtures/g4/english/teacher-reassembled.docx",
    },
  };
  if (fixture.blocks.length !== 439 || fixture.questions.length !== 63
      || fixture.standardModules.length !== 3 || fixture.questionSectionContainers.length !== 4) {
    throw new Error("source_fixture_contract_mismatch");
  }
  await fs.mkdir(path.dirname(output), { recursive: true });
  await fs.writeFile(output, `${JSON.stringify(fixture, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify({ output, blocks: blocks.length, questions: fixture.questions.length })}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`);
  process.exitCode = 1;
});
