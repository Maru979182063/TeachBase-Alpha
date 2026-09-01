import fs from "node:fs";
import path from "node:path";

const root = path.resolve("backend/teachbase-server/src/main/java");
const chinese = /[\u3400-\u9fff]/u;

function walk(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const absolute = path.join(directory, entry.name);
    return entry.isDirectory() ? walk(absolute) : [absolute];
  });
}

// 不能用正则直接查找 //，否则会把字符串中的 https:// 误判成注释。
function extractComments(source) {
  const comments = [];
  let index = 0;

  while (index < source.length) {
    if (source.startsWith('"""', index)) {
      index += 3;
      while (index < source.length && !source.startsWith('"""', index)) {
        index++;
      }
      index += source.startsWith('"""', index) ? 3 : 0;
      continue;
    }
    if (source[index] === '"' || source[index] === "'") {
      const quote = source[index++];
      while (index < source.length) {
        if (source[index] === "\\") {
          index += 2;
        } else if (source[index++] === quote) {
          break;
        }
      }
      continue;
    }
    if (source.startsWith("//", index)) {
      const start = index;
      index = source.indexOf("\n", index + 2);
      if (index < 0) {
        index = source.length;
      }
      comments.push(source.slice(start, index));
      continue;
    }
    if (source.startsWith("/*", index)) {
      const start = index;
      const end = source.indexOf("*/", index + 2);
      index = end < 0 ? source.length : end + 2;
      comments.push(source.slice(start, index));
      continue;
    }
    index++;
  }

  return comments;
}

const javaFiles = walk(root).filter((candidate) => candidate.endsWith(".java"));
const missing = [];
const untranslated = [];

for (const file of javaFiles) {
  const source = fs.readFileSync(file, "utf8");
  const comments = extractComments(source);
  const relative = path.relative(process.cwd(), file).replaceAll("\\", "/");
  if (!comments.some((value) => chinese.test(value))) {
    missing.push(relative);
  }
  if (comments.some((value) => !chinese.test(value))) {
    untranslated.push(relative);
  }
}

if (missing.length > 0 || untranslated.length > 0) {
  if (missing.length > 0) {
    console.error("以下生产 Java 文件缺少中文维护注释：");
    for (const file of missing) {
      console.error(`- ${file}`);
    }
  }
  if (untranslated.length > 0) {
    console.error("以下生产 Java 文件仍包含纯英文注释块：");
    for (const file of untranslated) {
      console.error(`- ${file}`);
    }
  }
  process.exitCode = 1;
} else {
  console.log(JSON.stringify({
    schemaVersion: 1,
    status: "passed",
    javaFileCount: javaFiles.length,
    chineseCommentCoverage: javaFiles.length,
    untranslatedCommentBlocks: 0,
  }, null, 2));
}
