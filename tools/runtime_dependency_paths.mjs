/**
 * 用途：
 * - 统一解析运行时依赖路径，避免把当前机器用户名和绝对目录写死在脚本里。
 * - 优先采用显式环境变量，其次从当前 Node 运行时反推出 bundled 依赖目录。
 */

import fs from "node:fs";
import path from "node:path";

function firstExistingPath(candidates) {
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return null;
}

function looksLikeDependenciesRoot(candidate) {
  if (!candidate || !fs.existsSync(candidate)) {
    return false;
  }
  return (
    fs.existsSync(path.join(candidate, "python", "python.exe")) ||
    fs.existsSync(path.join(candidate, "node", "bin", "node.exe")) ||
    fs.existsSync(path.join(candidate, "node", "node_modules"))
  );
}

function resolveDependenciesRoot() {
  const explicitRoot = process.env.RUNTIME_BACKBONE_DEPENDENCIES_ROOT || "";
  if (looksLikeDependenciesRoot(explicitRoot)) {
    return explicitRoot;
  }

  if (process.execPath) {
    const execDerivedRoot = path.resolve(path.dirname(process.execPath), "..", "..");
    if (looksLikeDependenciesRoot(execDerivedRoot)) {
      return execDerivedRoot;
    }
  }

  const userHome = process.env.USERPROFILE || process.env.HOME || "";
  const cachedRoot = userHome
    ? path.join(userHome, ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies")
    : null;
  if (looksLikeDependenciesRoot(cachedRoot)) {
    return cachedRoot;
  }

  return null;
}

export function resolveBundledPythonPath() {
  const dependenciesRoot = resolveDependenciesRoot();
  return firstExistingPath([
    process.env.RUNTIME_BACKBONE_PYTHON,
    dependenciesRoot && path.join(dependenciesRoot, "python", "python.exe"),
  ]);
}

export function resolveBundledNodeModulesPath() {
  const dependenciesRoot = resolveDependenciesRoot();
  return firstExistingPath([
    process.env.RUNTIME_BACKBONE_NODE_MODULES,
    dependenciesRoot && path.join(dependenciesRoot, "node", "node_modules"),
  ]);
}
