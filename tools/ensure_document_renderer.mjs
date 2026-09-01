import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const workspaceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const vendorRoot = path.join(workspaceRoot, "tools", "vendor", "document-renderer");

const releases = {
  pandoc: {
    version: "3.11",
    windows: {
      archive: "pandoc-3.11-windows-x86_64.zip",
      sha256: "2ab72baf2399450e148ddf7a2a8689806c42e1bba71862b57e220fd9b8456d3d",
      url: "https://github.com/jgm/pandoc/releases/download/3.11/pandoc-3.11-windows-x86_64.zip",
      executable: "pandoc.exe",
    },
    linux: {
      archive: "pandoc-3.11-linux-amd64.tar.gz",
      sha256: "37edb3bbcf722f921a009941bf5874e2e0c09263226c9b4a2d980788cb062ab6",
      url: "https://github.com/jgm/pandoc/releases/download/3.11/pandoc-3.11-linux-amd64.tar.gz",
      executable: "pandoc",
    },
  },
  typst: {
    version: "0.15.1",
    windows: {
      archive: "typst-x86_64-pc-windows-msvc.zip",
      sha256: "19ce3551153c2fe7ee9fa2f95208310c8f4d3209fedb699e0333faf8913f6736",
      url: "https://github.com/typst/typst/releases/download/v0.15.1/typst-x86_64-pc-windows-msvc.zip",
      executable: "typst.exe",
    },
    linux: {
      archive: "typst-x86_64-unknown-linux-musl.tar.xz",
      sha256: "a6d077d0a95eed5a2eba715b2dae06be954f624ccbf85758a03f389ded33118c",
      url: "https://github.com/typst/typst/releases/download/v0.15.1/typst-x86_64-unknown-linux-musl.tar.xz",
      executable: "typst",
    },
  },
};

function platformKey() {
  if (process.arch !== "x64") throw new Error(`unsupported_renderer_architecture:${process.arch}`);
  if (process.platform === "win32") return "windows";
  if (process.platform === "linux") return "linux";
  throw new Error(`unsupported_renderer_platform:${process.platform}`);
}

async function sha256(file) {
  const hash = crypto.createHash("sha256");
  const handle = await fs.open(file, "r");
  try {
    for await (const chunk of handle.createReadStream()) hash.update(chunk);
  } finally {
    await handle.close();
  }
  return hash.digest("hex");
}

async function download(url, target) {
  const response = await fetch(url, { headers: { "User-Agent": "TeachBase-Renderer-Bootstrap" } });
  if (!response.ok || !response.body) throw new Error(`renderer_download_failed:${response.status}`);
  const temporary = `${target}.${crypto.randomUUID()}.tmp`;
  const handle = await fs.open(temporary, "wx");
  try {
    for await (const chunk of response.body) await handle.write(chunk);
  } finally {
    await handle.close();
  }
  await fs.rename(temporary, target);
}

async function run(command, args, cwd) {
  const child = spawn(command, args, { cwd, stdio: ["ignore", "pipe", "pipe"] });
  const stdout = [];
  const stderr = [];
  child.stdout.on("data", (chunk) => stdout.push(chunk));
  child.stderr.on("data", (chunk) => stderr.push(chunk));
  const code = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", resolve);
  });
  if (code !== 0) throw new Error(`renderer_extract_failed:${Buffer.concat(stderr).toString("utf8")}`);
  return Buffer.concat(stdout).toString("utf8");
}

async function findFile(root, filename) {
  for (const entry of await fs.readdir(root, { withFileTypes: true })) {
    const candidate = path.join(root, entry.name);
    if (entry.isDirectory()) {
      const nested = await findFile(candidate, filename);
      if (nested) return nested;
    } else if (entry.name === filename) return candidate;
  }
  return null;
}

async function ensureTool(name, platform) {
  const release = releases[name];
  const asset = release[platform];
  const root = path.join(vendorRoot, name, release.version, platform);
  const marker = path.join(root, "verified.json");
  try {
    const verified = JSON.parse(await fs.readFile(marker, "utf8"));
    const executable = path.join(root, verified.executableRelativePath);
    await fs.access(executable);
    return { name, version: release.version, executable };
  } catch {
    // A missing or incomplete cache is rebuilt from the pinned release.
  }
  await fs.rm(root, { recursive: true, force: true });
  await fs.mkdir(root, { recursive: true });
  const archive = path.join(root, asset.archive);
  await download(asset.url, archive);
  const actualHash = await sha256(archive);
  if (actualHash !== asset.sha256) {
    await fs.rm(root, { recursive: true, force: true });
    throw new Error(`renderer_checksum_mismatch:${name}`);
  }
  const extracted = path.join(root, "extracted");
  await fs.mkdir(extracted, { recursive: true });
  await run("tar", ["-xf", archive, "-C", extracted], root);
  const executable = await findFile(extracted, asset.executable);
  if (!executable) throw new Error(`renderer_executable_missing:${name}`);
  if (platform === "linux") await fs.chmod(executable, 0o755);
  const executableRelativePath = path.relative(root, executable);
  await fs.writeFile(marker, `${JSON.stringify({
    schemaVersion: 1,
    name,
    version: release.version,
    archiveSha256: asset.sha256,
    executableRelativePath,
  }, null, 2)}\n`, "utf8");
  return { name, version: release.version, executable };
}

async function main() {
  const platform = platformKey();
  const tools = await Promise.all([ensureTool("pandoc", platform), ensureTool("typst", platform)]);
  process.stdout.write(`${JSON.stringify({
    schemaVersion: 1,
    platform,
    tools: Object.fromEntries(tools.map((tool) => [tool.name, { version: tool.version, executable: tool.executable }])),
  }, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
