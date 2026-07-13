import fs from "node:fs/promises";
import path from "node:path";

import {
  expect,
  runProcess,
  workspaceRoot,
} from "../helpers/runtime_testkit.mjs";
import { resolveBundledPythonPath } from "../../tools/runtime_dependency_paths.mjs";
import {
  findCommandOnPath,
  isSafeTestDatabaseUrl,
  resolvePgTool,
} from "./release_gate_shared.mjs";

const requiredScripts = [
  "tools/runtime_backbone_store.mjs",
  "tools/runtime_backbone_postgres_store.mjs",
  "tools/mock_workbench_api_server.mjs",
  "tools/runtime_backbone_validation_checks.mjs",
  "tools/visual_transcription_core.py",
  "tools/assetize_question_images.py",
  "tools/source_refs_json_merge.py",
  "tools/question_visual_structure_contract.py",
  "tools/compose_legacy_stem_md.py",
];

function parseMajorVersion(rawVersion) {
  const match = String(rawVersion || "").match(/(\d+)\./);
  return match ? Number(match[1]) : 0;
}

export function registerTests(register) {
  register({
    id: "RG-PREFLIGHT-01",
    suite: "release_gate_preflight",
    title: "Release gate environment has safe local-only database targeting and usable tool fallbacks",
    required: true,
    async run({ harness }) {
      const warnings = [];
      const pythonExe = resolveBundledPythonPath() || process.env.PYTHON || "python";
      const [pythonVersion, dockerPath, dockerComposePlugin, dockerComposeBinary, localPgDump, localPgRestore] =
        await Promise.all([
          runProcess(pythonExe, ["--version"]),
          findCommandOnPath("docker"),
          runProcess("docker", ["compose", "version"]),
          findCommandOnPath("docker-compose"),
          resolvePgTool("pg_dump"),
          resolvePgTool("pg_restore"),
        ]);

      const outputsRoot = path.join(
        workspaceRoot,
        "outputs",
        "test_runs",
        "release_gate",
        "preflight_probe"
      );
      await fs.mkdir(outputsRoot, { recursive: true });
      await fs.writeFile(
        path.join(outputsRoot, "write_probe.txt"),
        "release_gate_preflight",
        "utf8"
      );

      for (const relativePath of requiredScripts) {
        await fs.access(path.join(workspaceRoot, relativePath));
      }

      const nodeMajor = parseMajorVersion(process.version);
      expect(nodeMajor >= 20, `node_version_too_old:${process.version}`);
      expect(
        pythonVersion.code === 0,
        `python_not_available:${pythonVersion.stderr || pythonVersion.stdout}`
      );
      const pythonMajor = parseMajorVersion(
        `${pythonVersion.stdout}${pythonVersion.stderr}`
      );
      expect(
        pythonMajor >= 3,
        `python_version_too_old:${pythonVersion.stdout || pythonVersion.stderr}`
      );

      const dockerComposeReady =
        dockerComposePlugin.code === 0 || Boolean(dockerComposeBinary);
      const canDumpViaLocalTools = Boolean(localPgDump && localPgRestore);
      const canDumpViaDocker = Boolean(dockerPath) && dockerComposeReady;
      expect(
        canDumpViaLocalTools || canDumpViaDocker,
        "backup_restore_tooling_missing:need_pg_dump_pg_restore_or_docker_fallback"
      );
      if (!process.env.DATABASE_URL_TEST) {
        warnings.push("DATABASE_URL_TEST absent; embedded Postgres fallback will be used");
      } else {
        const safety = isSafeTestDatabaseUrl(process.env.DATABASE_URL_TEST);
        expect(safety.ok, safety.reason);
      }

      const database = await harness.createPostgresDatabase("release_gate_preflight_test");
      const safety = isSafeTestDatabaseUrl(database.connectionString);
      expect(safety.ok, `embedded_postgres_connection_should_be_safe:${safety.reason}`);

      if (!dockerPath) {
        warnings.push("Docker not available; backup restore will prefer local pg_dump/pg_restore");
      } else if (!dockerComposeReady) {
        warnings.push("Docker Compose unavailable; Docker fallback is limited to direct docker run");
      }

      return {
        nodeVersion: process.version,
        pythonVersion: (pythonVersion.stdout || pythonVersion.stderr).trim(),
        dockerAvailable: Boolean(dockerPath),
        dockerComposeAvailable: dockerComposeReady,
        pgDump: localPgDump || "docker_fallback_only",
        pgRestore: localPgRestore || "docker_fallback_only",
        maskedDatabase: database.maskedConnectionString,
        warnings,
      };
    },
  });
}
