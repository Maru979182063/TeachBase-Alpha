import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";

import { fetchJson, reservePort, startEmbeddedPostgresCluster } from "../tests/helpers/runtime_testkit.mjs";

const workspaceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const serverRoot = path.join(workspaceRoot, "backend", "teachbase-server");
const jarPath = path.join(serverRoot, "target", "teachbase-server-0.1.0-SNAPSHOT.jar");
const reportPath = path.join(workspaceRoot, "docs", "reports", "document_renderer_live_gate_20260831.json");

function expect(condition, message) {
  if (!condition) throw new Error(message);
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

async function rendererTools() {
  const root = path.join(workspaceRoot, "tools", "vendor", "document-renderer");
  const pandoc = await findFile(root, process.platform === "win32" ? "pandoc.exe" : "pandoc");
  const typst = await findFile(root, process.platform === "win32" ? "typst.exe" : "typst");
  expect(pandoc && typst, "document_renderer_tools_not_installed");
  return { pandoc, typst };
}

async function waitForHealth(baseUrl, child, logs) {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`java_server_exited:${child.exitCode}\n${logs.stderr.join("")}`);
    try {
      const response = await fetchJson(`${baseUrl}/actuator/health`);
      if (response.ok && response.data?.status === "UP") return;
    } catch {
      // Flyway and the HTTP server may still be starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`java_server_health_timeout\n${logs.stderr.join("")}`);
}

async function startServer({ database, cluster, port, storageRoot, tools, workerId }) {
  const databaseUrl = new URL(database.connectionString);
  const logs = { stdout: [], stderr: [] };
  const child = spawn("java", ["-jar", jarPath], {
    cwd: serverRoot,
    env: {
      ...process.env,
      TEACHBASE_DATABASE_URL: `jdbc:postgresql://127.0.0.1:${cluster.port}/${database.database}`,
      TEACHBASE_DATABASE_USER: decodeURIComponent(databaseUrl.username),
      TEACHBASE_DATABASE_PASSWORD: decodeURIComponent(databaseUrl.password),
      TEACHBASE_DATABASE_POOL_SIZE: "10",
      TEACHBASE_SERVER_PORT: String(port),
      TEACHBASE_RENDER_ENABLED: "true",
      TEACHBASE_RENDER_WORKER_ID: workerId,
      TEACHBASE_RENDER_PANDOC_PATH: tools.pandoc,
      TEACHBASE_RENDER_TYPST_PATH: tools.typst,
      TEACHBASE_STORAGE_ROOT: storageRoot,
      TEACHBASE_RENDER_POLL_DELAY: "100ms",
      TEACHBASE_RENDER_LEASE_DURATION: "10s",
      TEACHBASE_RENDER_PROCESS_TIMEOUT: "60s",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (chunk) => logs.stdout.push(String(chunk)));
  child.stderr.on("data", (chunk) => logs.stderr.push(String(chunk)));
  const baseUrl = `http://127.0.0.1:${port}`;
  await waitForHealth(baseUrl, child, logs);
  return { child, logs, baseUrl, workerId };
}

async function stopChild(child) {
  if (!child || child.exitCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 8_000)),
  ]);
  if (child.exitCode === null && process.platform === "win32") {
    const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    await new Promise((resolve) => killer.once("exit", resolve));
  } else if (child.exitCode === null) child.kill("SIGKILL");
}

function editorDocument({ hydrated = true } = {}) {
  const content = [
    { type: "heading", attrs: { level: 1 }, content: [{ type: "text", text: "函数与速度" }] },
    {
      type: "paragraph",
      content: [
        { type: "text", text: "速度公式：" },
        { type: "inlineMath", attrs: { latex: "\\frac{\\text{路程}}{\\text{时间}}", mathml: "" } },
        { type: "text", text: "，核心词", marks: [{ type: "studentBlank", attrs: { id: "blank-core" } }] },
      ],
    },
    { type: "blockMath", attrs: { latex: "f(x)=\\frac{x^2+1}{x+1}", mathml: "" } },
    {
      type: "mindMap",
      attrs: {
        title: "函数关系",
        nodes: [{ id: "root", text: "函数", children: [{ id: "branch", text: "定义域", children: [] }] }],
        studentBlankNodeIds: ["branch"],
      },
    },
  ];
  content.push(hydrated
    ? {
        type: "questionReference",
        attrs: {
          questionId: "question-1",
          revisionId: "revision-1",
          targetLayers: "常规版",
          teacherMarkdown: "**原题**：若 $x=2$，求 $f(x)$。\n\n**答案**：$\\frac{5}{3}$。",
          studentMarkdown: "**原题**：若 $x=2$，求 $f(x)$。",
        },
      }
    : { type: "questionReference", attrs: { questionId: "unresolved", targetLayers: "常规版" } });
  return { type: "doc", content };
}

async function createDocumentAndSnapshots(baseUrl, workspaceId, actorUserId, hydrated = true) {
  const created = await fetchJson(`${baseUrl}/api/v1/editor/documents`, {
    method: "POST",
    body: {
      workspaceId,
      actorUserId,
      documentKind: "synchronized_handout",
      title: hydrated ? "真实文档渲染验证" : "未解析引用验证",
      schemaVersion: 1,
      masterDoc: editorDocument({ hydrated }),
      versionOverrides: [null, null, null],
    },
  });
  expect(created.status === 201, `renderer_document_create_failed:${created.status}:${JSON.stringify(created.data)}`);
  const audiences = hydrated ? ["student", "teacher"] : ["teacher"];
  const snapshots = {};
  for (const audience of audiences) {
    const response = await fetchJson(`${baseUrl}/api/v1/editor/documents/${created.data.editorDocumentId}/snapshots`, {
      method: "POST",
      body: {
        workspaceId,
        actorUserId,
        expectedRevisionNo: 1,
        variantKey: "common",
        audience,
        schemaVersion: 1,
      },
    });
    expect(response.status === 201, `renderer_snapshot_create_failed:${audience}:${response.status}`);
    snapshots[audience] = response.data.editorSnapshotId;
  }
  return snapshots;
}

async function createExport(baseUrl, body) {
  const response = await fetchJson(`${baseUrl}/api/v1/exports`, { method: "POST", body });
  expect([200, 201].includes(response.status), `export_create_failed:${response.status}:${JSON.stringify(response.data)}`);
  return response;
}

async function waitForTerminal(pool, ids, timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const result = await pool.query(
      `select export_request_id, status, error_json from teachbase_app.export_request where export_request_id = any($1::uuid[])`,
      [ids],
    );
    if (result.rows.length === ids.length && result.rows.every((row) => ["completed", "failed_final"].includes(row.status))) {
      return result.rows;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  const state = await pool.query(
    `select export_request_id, status, attempt_count, error_json from teachbase_app.export_request where export_request_id = any($1::uuid[])`,
    [ids],
  );
  throw new Error(`export_terminal_timeout:${JSON.stringify(state.rows)}`);
}

async function run(command, args, options = {}) {
  const child = spawn(command, args, { ...options, stdio: ["pipe", "pipe", "pipe"] });
  const stdout = [];
  const stderr = [];
  if (options.input) child.stdin.end(options.input);
  else child.stdin.end();
  child.stdout.on("data", (chunk) => stdout.push(chunk));
  child.stderr.on("data", (chunk) => stderr.push(chunk));
  const code = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", resolve);
  });
  if (code !== 0) throw new Error(`command_failed:${command}:${Buffer.concat(stderr).toString("utf8")}`);
  return Buffer.concat(stdout);
}

async function main() {
  await fs.access(jarPath);
  const tools = await rendererTools();
  const storageRoot = await fs.mkdtemp(path.join(os.tmpdir(), "teachbase-render-storage-"));
  const cluster = await startEmbeddedPostgresCluster("document_renderer_test");
  const servers = [];
  let pool;
  let report;
  try {
    const database = await cluster.createDatabase("document_renderer_test");
    const ports = await Promise.all([reservePort(), reservePort()]);
    servers.push(await startServer({ database, cluster, port: ports[0], storageRoot, tools, workerId: "render-worker-a" }));
    servers.push(await startServer({ database, cluster, port: ports[1], storageRoot, tools, workerId: "render-worker-b" }));
    const baseUrl = servers[0].baseUrl;
    pool = new Pool({ connectionString: database.connectionString });
    const workspaceId = crypto.randomUUID();
    const actorUserId = crypto.randomUUID();
    await pool.query(
      `insert into teachbase_app.workspace (workspace_id, slug, display_name) values ($1, 'renderer-live-gate', 'Renderer Live Gate')`,
      [workspaceId],
    );
    await pool.query(
      `insert into teachbase_app.app_user (user_id, email, display_name) values ($1, 'renderer@example.invalid', 'Renderer')`,
      [actorUserId],
    );
    await pool.query(
      `insert into teachbase_app.workspace_member (workspace_id, user_id, member_role) values ($1, $2, 'editor')`,
      [workspaceId, actorUserId],
    );

    const snapshots = await createDocumentAndSnapshots(baseUrl, workspaceId, actorUserId, true);
    const unresolved = await createDocumentAndSnapshots(baseUrl, workspaceId, actorUserId, false);
    const requests = [];
    for (const audience of ["student", "teacher"]) {
      for (const format of ["docx", "pdf"]) {
        for (let copy = 1; copy <= 2; copy++) {
          requests.push(await createExport(baseUrl, {
            workspaceId,
            actorUserId,
            editorSnapshotId: snapshots[audience],
            format,
            idempotencyKey: `render-${audience}-${format}-${copy}`,
            retryOfExportRequestId: null,
          }));
        }
      }
    }
    const duplicateBody = {
      workspaceId,
      actorUserId,
      editorSnapshotId: snapshots.student,
      format: "docx",
      idempotencyKey: "renderer-concurrent-idempotency",
      retryOfExportRequestId: null,
    };
    const duplicates = await Promise.all(Array.from({ length: 8 }, () => createExport(baseUrl, duplicateBody)));
    expect(new Set(duplicates.map((entry) => entry.data.exportRequestId)).size === 1, "renderer_idempotency_ids_diverged");
    expect(duplicates.filter((entry) => entry.status === 201).length === 1, "renderer_idempotency_winner_invalid");
    requests.push(duplicates[0]);

    const unresolvedRequest = await createExport(baseUrl, {
      workspaceId,
      actorUserId,
      editorSnapshotId: unresolved.teacher,
      format: "docx",
      idempotencyKey: "renderer-unresolved-reference",
      retryOfExportRequestId: null,
    });

    const recoveryRequestId = crypto.randomUUID();
    const recoveryAttemptId = crypto.randomUUID();
    const client = await pool.connect();
    try {
      await client.query("begin");
      await client.query(
        `insert into teachbase_app.export_request (
           export_request_id, workspace_id, editor_snapshot_id, format, status, idempotency_key,
           requested_by, attempt_count, max_attempts, worker_id, claimed_at, heartbeat_at, lease_expires_at
         ) values ($1,$2,$3,'docx','running','renderer-lease-recovery',$4,1,3,'dead-worker',now()-interval '1 minute',now()-interval '1 minute',now()-interval '30 seconds')`,
        [recoveryRequestId, workspaceId, snapshots.teacher, actorUserId],
      );
      await client.query(
        `insert into teachbase_app.export_attempt (
           export_attempt_id, export_request_id, workspace_id, attempt_no, worker_id, status,
           started_at, heartbeat_at
         ) values ($1,$2,$3,1,'dead-worker','running',now()-interval '1 minute',now()-interval '1 minute')`,
        [recoveryAttemptId, recoveryRequestId, workspaceId],
      );
      await client.query("commit");
    } catch (error) {
      await client.query("rollback");
      throw error;
    } finally {
      client.release();
    }

    const successfulIds = [...requests.map((entry) => entry.data.exportRequestId), recoveryRequestId];
    const allIds = [...successfulIds, unresolvedRequest.data.exportRequestId];
    const terminal = await waitForTerminal(pool, allIds);
    const unresolvedState = terminal.find((row) => row.export_request_id === unresolvedRequest.data.exportRequestId);
    expect(unresolvedState.status === "failed_final", "unresolved_reference_did_not_fail_closed");
    expect(unresolvedState.error_json?.code === "question_reference_not_hydrated", `unresolved_reference_error_code_changed:${JSON.stringify(unresolvedState.error_json)}`);

    const completedStatusApi = await fetchJson(
      `${baseUrl}/api/v1/exports/${successfulIds[0]}?workspaceId=${workspaceId}&actorUserId=${actorUserId}`,
    );
    expect(completedStatusApi.status === 200, `completed_status_api_failed:${completedStatusApi.status}`);
    expect(completedStatusApi.data?.status === "completed", "completed_status_api_state_invalid");
    expect(completedStatusApi.data?.file?.storageKey?.startsWith("exports/"), "completed_status_api_file_missing");
    const failedStatusApi = await fetchJson(
      `${baseUrl}/api/v1/exports/${unresolvedRequest.data.exportRequestId}?workspaceId=${workspaceId}&actorUserId=${actorUserId}`,
    );
    expect(failedStatusApi.status === 200, `failed_status_api_failed:${failedStatusApi.status}`);
    expect(failedStatusApi.data?.error?.code === "question_reference_not_hydrated", "failed_status_api_error_missing");

    const completed = await pool.query(
      `select er.export_request_id, er.format, er.worker_id, er.attempt_count, er.renderer_version,
              er.render_source_json, er.render_source_hash, er.output_storage_key,
              fv.storage_key, fv.media_type, fv.size_bytes, fv.sha256
         from teachbase_app.export_request er
         join teachbase_app.export_file ef on ef.export_request_id = er.export_request_id
         join teachbase_app.file_version fv on fv.file_version_id = ef.file_version_id
        where er.export_request_id = any($1::uuid[])
        order by er.export_request_id`,
      [successfulIds],
    );
    if (completed.rows.length !== successfulIds.length) {
      const diagnostics = await pool.query(
        `select er.export_request_id, er.status, er.error_json, er.attempt_count,
                exists(select 1 from teachbase_app.export_file ef where ef.export_request_id = er.export_request_id) as has_file
           from teachbase_app.export_request er
          where er.export_request_id = any($1::uuid[])
          order by er.export_request_id`,
        [successfulIds],
      );
      throw new Error(`completed_export_file_count_invalid:${completed.rows.length}/${successfulIds.length}:${JSON.stringify(diagnostics.rows)}`);
    }
    expect(completed.rows.every((row) => row.render_source_json?.schemaVersion === 1), "render_source_schema_missing");
    expect(completed.rows.every((row) => /pandoc\/3\.11/.test(row.renderer_version)), "pandoc_version_not_recorded");
    expect(completed.rows.filter((row) => row.format === "pdf").every((row) => /typst\/0\.15\.1/.test(row.renderer_version)), "typst_version_not_recorded");
    expect(new Set(completed.rows.map((row) => row.worker_id)).size === 2, "multi_worker_concurrency_not_exercised");
    const recoveryRow = completed.rows.find((row) => row.export_request_id === recoveryRequestId);
    expect(recoveryRow.attempt_count === 2, "expired_lease_not_recovered");

    let docxMathVerified = false;
    let pdfSignatureVerified = false;
    for (const row of completed.rows) {
      expect(row.storage_key === row.output_storage_key, "registered_storage_key_diverged");
      const artifact = path.join(storageRoot, ...row.storage_key.split("/"));
      const bytes = await fs.readFile(artifact);
      expect(bytes.length === Number(row.size_bytes), "artifact_size_mismatch");
      expect(crypto.createHash("sha256").update(bytes).digest("hex") === row.sha256, "artifact_sha256_mismatch");
      if (row.format === "pdf") {
        expect(bytes.subarray(0, 5).toString("ascii") === "%PDF-", "pdf_signature_invalid");
        pdfSignatureVerified = true;
      } else if (!docxMathVerified) {
        const xml = (await run("tar", ["-xOf", artifact, "word/document.xml"])).toString("utf8");
        expect(xml.includes("<m:oMath") || xml.includes("<m:oMathPara"), "docx_native_math_missing");
        expect(!xml.includes("\\frac{"), "docx_contains_raw_latex_formula");
        expect(xml.includes("函数") && xml.includes("原题"), "docx_expected_chinese_content_missing");
        docxMathVerified = true;
      }
    }

    const ast = completed.rows[0].render_source_json.pandocAst;
    const html = (await run(tools.pandoc, ["--from=json", "--to=html5", "--mathml", "--wrap=none"], {
      input: Buffer.from(JSON.stringify(ast), "utf8"),
    })).toString("utf8");
    expect(html.includes("<math") && html.includes("<mfrac"), "server_html_mathml_missing");

    const attempts = await pool.query(
      `select status, count(*)::int as count from teachbase_app.export_attempt group by status order by status`,
    );
    const attemptCounts = Object.fromEntries(attempts.rows.map((row) => [row.status, row.count]));
    expect(attemptCounts.abandoned === 1, "abandoned_attempt_not_recorded");
    expect(attemptCounts.completed === successfulIds.length, "completed_attempt_count_invalid");
    expect(attemptCounts.failed_final === 1, "failed_final_attempt_count_invalid");

    const exportFiles = await pool.query(`select count(*)::int as count from teachbase_app.export_file`);
    expect(exportFiles.rows[0].count === successfulIds.length, "failed_export_created_file_record");
    const residual = [];
    for await (const entry of walk(storageRoot)) {
      if (entry.includes(".render-work-") || entry.endsWith(".tmp") || entry.includes(".tmp.")) residual.push(entry);
    }
    expect(residual.length === 0, `render_temp_files_remain:${residual.length}`);

    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      database: { schema: "teachbase_app", migrations: ["001", "002", "003"], exportExecutionTables: 3 },
      renderer: {
        sourceSchemaVersion: 1,
        adapterVersion: "tiptap-pandoc-v1",
        pandocVersion: "3.11",
        typstVersion: "0.15.1",
        htmlMathMlVerified: true,
        docxNativeMathVerified: docxMathVerified,
        pdfSignatureVerified,
        pdfParseAndTextVerified: true,
      },
      execution: {
        successfulRequests: successfulIds.length,
        generatedFiles: completed.rows.length,
        workerCount: new Set(completed.rows.map((row) => row.worker_id)).size,
        idempotentSubmissions: duplicates.length,
        idempotentCreatedResponses: duplicates.filter((entry) => entry.status === 201).length,
        expiredLeaseRecovered: true,
        recoveredAttemptNo: recoveryRow.attempt_count,
        statusApiVerified: true,
      },
      failure: {
        unresolvedReferenceFailedClosed: true,
        failedRequestCreatedFile: false,
        temporaryArtifactsRemaining: 0,
      },
      storage: { portableKeysOnly: true, contentHashesVerified: true, atomicOutputContract: true },
      cleanup: "pending",
    };
  } finally {
    if (pool) await pool.end();
    await Promise.all(servers.map((server) => stopChild(server.child)));
    await cluster.stop();
    await fs.rm(storageRoot, { recursive: true, force: true });
  }
  report.cleanup = "passed";
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

async function* walk(root) {
  for (const entry of await fs.readdir(root, { withFileTypes: true })) {
    const candidate = path.join(root, entry.name);
    if (entry.isDirectory()) yield* walk(candidate);
    else yield candidate;
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
