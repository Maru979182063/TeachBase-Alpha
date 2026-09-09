import fs from "node:fs/promises";
import path from "node:path";

function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1]) throw new Error(`missing_argument:${name}`);
  return path.resolve(process.argv[index + 1]);
}

async function main() {
  const source = argument("--source");
  const output = argument("--output");
  const composition = JSON.parse(await fs.readFile(path.join(source, "composition.json"), "utf8"));
  const blocks = (await fs.readFile(path.join(source, "content-index.jsonl"), "utf8"))
    .trim().split(/\r?\n/).map((line) => JSON.parse(line)).map((block) => ({
      blockId: block.blockId,
      sourceIndex: block.sourceIndex,
      kind: block.kind ?? "paragraph",
      xmlSha256: block.xmlSha256 ?? null,
    }));
  const fixture = {
    schema: "teachbase.g4-circle-regression.v1",
    documentKey: composition.documentKey,
    title: "圆的方程",
    blocks,
    standardModules: composition.standardModules,
    questions: composition.questions,
    ordinaryPlacements: composition.ordinaryPlacements,
    topLevelSequence: composition.topLevelSequence,
    validation: composition.validation,
    preservationInput: composition.preservationInput,
    teacherReassembly: composition.teacherReassembly,
  };
  if (blocks.length !== 320 || fixture.questions.length !== 31
      || fixture.standardModules.length !== 3 || !fixture.validation.coverageExactlyOnce) {
    throw new Error("circle_fixture_contract_mismatch");
  }
  await fs.mkdir(path.dirname(output), { recursive: true });
  await fs.writeFile(output, `${JSON.stringify(fixture, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify({ output, blocks: blocks.length, questions: fixture.questions.length })}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`);
  process.exitCode = 1;
});
