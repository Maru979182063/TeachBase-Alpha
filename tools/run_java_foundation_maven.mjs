import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const workspaceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const serverRoot = path.join(workspaceRoot, "backend", "teachbase-server");
const locator = process.platform === "win32" ? "where.exe" : "which";
const located = spawnSync(locator, ["javac"], { encoding: "utf8" });

if (located.status !== 0) {
  process.stderr.write("Java 21 javac was not found on PATH.\n");
  process.exit(1);
}

const javacCandidate = located.stdout.split(/\r?\n/).find(Boolean);
const javacPath = fs.realpathSync(javacCandidate);
const javaHome = path.dirname(path.dirname(javacPath));
const javaExecutable = path.join(javaHome, "bin", process.platform === "win32" ? "java.exe" : "java");
const version = spawnSync(javaExecutable, ["-version"], { encoding: "utf8" });
const versionText = `${version.stdout || ""}\n${version.stderr || ""}`;

if (version.status !== 0 || !/version "21\./.test(versionText)) {
  process.stderr.write(`Java 21 is required; javac resolved to ${javacPath}.\n`);
  process.exit(1);
}

const mavenCommand = process.platform === "win32" ? "mvn.cmd" : "mvn";
const mavenArgs = process.argv.slice(2);
const result = spawnSync(mavenCommand, mavenArgs.length ? mavenArgs : ["package"], {
  cwd: serverRoot,
  env: { ...process.env, JAVA_HOME: javaHome },
  stdio: "inherit",
  shell: process.platform === "win32",
});

if (result.error) {
  process.stderr.write(`${result.error.message}\n`);
}
process.exit(result.status ?? 1);
