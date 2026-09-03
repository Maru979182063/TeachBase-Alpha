import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";

import { fetchJson, reservePort, startEmbeddedPostgresCluster } from "../tests/helpers/runtime_testkit.mjs";

const workspaceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const serverRoot = path.join(workspaceRoot, "backend", "teachbase-server");
const jarPath = path.join(serverRoot, "target", "teachbase-server-0.1.0-SNAPSHOT.jar");
const reportPath = path.join(workspaceRoot, "docs", "reports", "editor_backend_live_gate_20260831.json");

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

async function waitForHealth(baseUrl, child, logs) {
  const deadline = Date.now() + 45_000;
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
  } else if (child.exitCode === null) {
    child.kill("SIGKILL");
  }
}

function editorDocument(label) {
  return {
    type: "doc",
    content: [
      {
        type: "paragraph",
        content: [
          { type: "text", text: label },
          { type: "text", text: "速度", marks: [{ type: "studentBlank", attrs: { id: "blank-speed" } }] },
          { type: "inlineMath", attrs: { latex: "\\frac{\\text{速度}}{\\text{时间}}", mathml: "" } },
        ],
      },
      {
        type: "mindMap",
        attrs: {
          moduleId: "mind-map-demo",
          revisionId: "local-draft",
          moduleType: "mindMap",
          blockType: "思维导图",
          title: "运动关系",
          nodes: [
            {
              id: "root",
              text: "运动",
              children: [{ id: "speed", text: "速度", children: [] }],
            },
          ],
          studentBlankNodeIds: "[\"speed\"]",
        },
      },
      { type: "questionReference", attrs: { questionId: "basic-only", revisionId: "revision-1", targetLayers: "基础版" } },
      { type: "questionReference", attrs: { questionId: "common-only", revisionId: "revision-1", targetLayers: "常规版" } },
      { type: "questionReference", attrs: { questionId: "common-standard", revisionId: "revision-1", targetLayers: "常用版" } },
      { type: "questionReference", attrs: { questionId: "all-variants", revisionId: "revision-1", targetLayers: "基础版,进阶版,常规版" } },
    ],
  };
}

async function main() {
  await fs.access(jarPath);
  const cluster = await startEmbeddedPostgresCluster("editor_backend_test");
  let child;
  let pool;
  let report;
  try {
    const database = await cluster.createDatabase("editor_backend_test");
    const databaseUrl = new URL(database.connectionString);
    const serverPort = await reservePort();
    const baseUrl = `http://127.0.0.1:${serverPort}`;
    const logs = { stdout: [], stderr: [] };
    child = spawn("java", ["-jar", jarPath], {
      cwd: serverRoot,
      env: {
        ...process.env,
        TEACHBASE_DATABASE_URL: `jdbc:postgresql://127.0.0.1:${cluster.port}/${database.database}`,
        TEACHBASE_DATABASE_USER: decodeURIComponent(databaseUrl.username),
        TEACHBASE_DATABASE_PASSWORD: decodeURIComponent(databaseUrl.password),
        TEACHBASE_DATABASE_POOL_SIZE: "12",
        TEACHBASE_SERVER_PORT: String(serverPort),
        TEACHBASE_RENDER_ENABLED: "false",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stdout.on("data", (chunk) => logs.stdout.push(String(chunk)));
    child.stderr.on("data", (chunk) => logs.stderr.push(String(chunk)));
    await waitForHealth(baseUrl, child, logs);

    pool = new Pool({ connectionString: database.connectionString });
    const workspaceId = crypto.randomUUID();
    const actorUserId = crypto.randomUUID();
    await pool.query(
      `insert into teachbase_app.workspace (workspace_id, slug, display_name) values ($1, 'editor-live-gate', 'Editor Live Gate')`,
      [workspaceId],
    );
    await pool.query(
      `insert into teachbase_app.app_user (user_id, email, display_name) values ($1, 'editor@example.invalid', 'Editor')`,
      [actorUserId],
    );
    await pool.query(
      `insert into teachbase_app.workspace_member (workspace_id, user_id, member_role) values ($1, $2, 'editor')`,
      [workspaceId, actorUserId],
    );

    const create = await fetchJson(`${baseUrl}/api/v1/editor/documents`, {
      method: "POST",
      body: {
        workspaceId,
        actorUserId,
        documentKind: "synchronized_handout",
        title: "公式与导图后端合同",
        schemaVersion: 1,
        masterDoc: editorDocument("revision-1:"),
        versionOverrides: [null, null, null],
      },
    });
    expect(create.status === 201, `create_status:${create.status}:${JSON.stringify(create.data)}`);
    expect(create.data?.draftVersion === 1, "initial_draft_version_not_one");
    expect(create.data?.baseRevisionNo === 0, "new_document_created_permanent_revision");
    expect(create.headers.etag === '"draft-1"', `initial_etag:${create.headers.etag}`);
    const documentId = create.data.editorDocumentId;

    const updateBody = {
      workspaceId,
      actorUserId,
      expectedDraftVersion: 1,
      schemaVersion: 1,
      masterDoc: editorDocument("revision-2:"),
      versionOverrides: [null, null, null],
    };
    const concurrent = await Promise.all([
      fetchJson(`${baseUrl}/api/v1/editor/documents/${documentId}/draft`, {
        method: "PUT", body: { ...updateBody, clientMutationId: "editor-live-concurrent-a" },
      }),
      fetchJson(`${baseUrl}/api/v1/editor/documents/${documentId}/draft`, {
        method: "PUT", body: { ...updateBody, clientMutationId: "editor-live-concurrent-b" },
      }),
    ]);
    expect(concurrent.filter((response) => response.status === 200).length === 1, "optimistic_update_winner_count_invalid");
    expect(concurrent.filter((response) => response.status === 409).length === 1, "optimistic_update_conflict_count_invalid");
    const conflict = concurrent.find((response) => response.status === 409);
    expect(conflict.data?.detail === "editor_draft_version_conflict", "draft_conflict_contract_changed");
    expect(conflict.data?.currentDraftVersion === 2, "draft_conflict_current_version_missing");

    const loaded = await fetchJson(
      `${baseUrl}/api/v1/editor/documents/${documentId}/draft?workspaceId=${workspaceId}&actorUserId=${actorUserId}`,
    );
    expect(loaded.status === 200 && loaded.data?.draftVersion === 2, "saved_draft_not_readable");
    expect(loaded.headers.etag === '"draft-2"', "saved_draft_etag_invalid");
    const persistedLayerValues = loaded.data.masterDoc.content
      .filter((node) => node.type === "questionReference")
      .map((node) => node.attrs.targetLayers);
    expect(
      JSON.stringify(persistedLayerValues) === JSON.stringify(["basic", "common", "common", "basic,advanced,common"]),
      `new_target_layers_not_canonical_keys:${JSON.stringify(persistedLayerValues)}`,
    );

    const snapshot = await fetchJson(`${baseUrl}/api/v1/editor/documents/${documentId}/snapshots`, {
      method: "POST",
      body: {
        workspaceId,
        actorUserId,
        expectedDraftVersion: 2,
        variantKey: "common",
        audience: "student",
        schemaVersion: 1,
      },
    });
    expect(snapshot.status === 201, `snapshot_status:${snapshot.status}:${JSON.stringify(snapshot.data)}`);
    expect(snapshot.data?.revisionNo === 1, "snapshot_revision_not_pinned");
    expect(snapshot.data?.frozenContent?.audience === "student", "snapshot_audience_not_frozen");
    const projectedQuestionIds = snapshot.data.frozenContent.projectedDoc.content
      .filter((node) => node.type === "questionReference")
      .map((node) => node.attrs.questionId);
    expect(
      JSON.stringify(projectedQuestionIds) === JSON.stringify(["common-only", "common-standard", "all-variants"]),
      `backend_variant_projection_invalid:${JSON.stringify(projectedQuestionIds)}`,
    );

    const staleSnapshot = await fetchJson(`${baseUrl}/api/v1/editor/documents/${documentId}/snapshots`, {
      method: "POST",
      body: {
        workspaceId,
        actorUserId,
        expectedDraftVersion: 1,
        variantKey: "common",
        audience: "teacher",
        schemaVersion: 1,
      },
    });
    expect(staleSnapshot.status === 409, "stale_snapshot_not_rejected");

    const exportBody = {
      workspaceId,
      actorUserId,
      editorSnapshotId: snapshot.data.editorSnapshotId,
      format: "DOCX",
      idempotencyKey: "editor-live-gate-common-student-docx",
      retryOfExportRequestId: null,
    };
    const exports = await Promise.all(
      Array.from({ length: 8 }, () => fetchJson(`${baseUrl}/api/v1/exports`, { method: "POST", body: exportBody })),
    );
    expect(exports.filter((response) => response.status === 201).length === 1, "export_create_winner_count_invalid");
    expect(exports.every((response) => [200, 201].includes(response.status)), "export_idempotency_status_failure");
    expect(new Set(exports.map((response) => response.data?.exportRequestId)).size === 1, "export_ids_diverged");
    const renderContract = await pool.query(
      `select render_contract_version, renderer_profile, renderer_version
         from teachbase_app.export_request
        where export_request_id = $1`,
      [exports[0].data.exportRequestId],
    );
    expect(renderContract.rows[0].render_contract_version === 1, "render_contract_version_invalid");
    expect(renderContract.rows[0].renderer_profile === "teachbase-document-v1", "renderer_profile_invalid");
    expect(renderContract.rows[0].renderer_version == null, "renderer_version_should_be_empty_before_execution");

    const invalidImage = await fetchJson(`${baseUrl}/api/v1/editor/documents`, {
      method: "POST",
      body: {
        workspaceId,
        actorUserId,
        documentKind: "independent_question_pack",
        title: "invalid image",
        schemaVersion: 1,
        masterDoc: { type: "doc", content: [{ type: "image", attrs: { src: "data:image/png;base64,AAAA" } }] },
        versionOverrides: [null, null, null],
      },
    });
    expect(invalidImage.status === 400, `base64_image_status:${invalidImage.status}`);
    expect(invalidImage.data?.detail === "image_source_must_reference_registered_asset", "base64_image_error_changed");

    const counts = await pool.query(
      `select
         (select count(*)::int from teachbase_app.editor_document) as documents,
         (select count(*)::int from teachbase_app.editor_variant) as variants,
         (select count(*)::int from teachbase_app.editor_revision) as revisions,
         (select count(*)::int from teachbase_app.editor_draft) as legacy_drafts,
         (select count(*)::int from teachbase_app.editor_working_draft) as working_drafts,
         (select count(*)::int from teachbase_app.editor_autosave_mutation) as mutations,
         (select count(*)::int from teachbase_app.editor_draft_checkpoint) as checkpoints,
         (select count(*)::int from teachbase_app.editor_preview_confirmation) as confirmations,
         (select count(*)::int from teachbase_app.editor_snapshot) as snapshots,
         (select count(*)::int from teachbase_app.export_request) as exports,
         (select count(*)::int from teachbase_app.audit_event where aggregate_type = 'editor_document') as audits`,
    );
    expect(counts.rows[0].documents === 1, "editor_document_count_invalid");
    expect(counts.rows[0].variants === 3, "editor_variant_count_invalid");
    expect(counts.rows[0].revisions === 1, "editor_revision_count_invalid");
    expect(counts.rows[0].legacy_drafts === 0, "legacy_editor_draft_should_not_be_created");
    expect(counts.rows[0].working_drafts === 1, "editor_working_draft_count_invalid");
    expect(counts.rows[0].mutations === 1, "editor_mutation_count_invalid");
    expect(counts.rows[0].checkpoints === 1, "editor_checkpoint_throttle_invalid");
    expect(counts.rows[0].confirmations === 1, "editor_confirmation_count_invalid");
    expect(counts.rows[0].snapshots === 1, "editor_snapshot_count_invalid");
    expect(counts.rows[0].exports === 1, "export_request_count_invalid");
    expect(counts.rows[0].audits === 2, "editor_document_audit_count_invalid");
    const commonVariant = await pool.query(
      `select display_name from teachbase_app.editor_variant where editor_document_id = $1 and variant_key = 'common'`,
      [documentId],
    );
    expect(commonVariant.rows[0]?.display_name === "常用版", "common_display_name_not_standardized");
    const aggregateAudits = await pool.query(
      `select aggregate_type, count(*)::int as count
         from teachbase_app.audit_event
        where aggregate_type in ('editor_snapshot', 'export_request')
        group by aggregate_type`,
    );
    const auditCounts = Object.fromEntries(aggregateAudits.rows.map((row) => [row.aggregate_type, row.count]));
    expect(auditCounts.editor_snapshot === 1, "editor_snapshot_audit_count_invalid");
    expect(auditCounts.export_request === 1, "export_request_audit_count_invalid");

    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      database: { schema: "teachbase_app", flywayThrough: "V008", editorWorkingDraftTables: 3 },
      editor: {
        model: "master-overrides-v1",
        contentSchemaVersion: 1,
        formulaSource: "latex",
        mindMapSource: "stable-node-tree",
        studentBlankAnnotations: "versioned",
        variants: counts.rows[0].variants,
        revisions: counts.rows[0].revisions,
        immutableSnapshots: counts.rows[0].snapshots,
        variantProjectionOwnedByBackend: true,
        canonicalVariantKeysPersisted: true,
        commonDisplayName: commonVariant.rows[0].display_name,
        legacyCommonLabelsReadable: ["常用版", "常规版"],
      },
      concurrency: { simultaneousUpdates: 2, successfulUpdates: 1, conflicts: 1, finalDraftVersion: 2 },
      export: {
        requests: counts.rows[0].exports,
        simultaneousSubmissions: exports.length,
        createdResponses: exports.filter((response) => response.status === 201).length,
        idempotent: true,
        generatedFiles: 0,
      },
      rendering: {
        contractVersion: renderContract.rows[0].render_contract_version,
        profile: renderContract.rows[0].renderer_profile,
        concreteEngineVersion: null,
        status: "admission_only_worker_disabled_for_contract_gate",
      },
      validation: {
        base64ImageRejected: true,
        legacyHtmlFieldsAcceptedForCompatibility: true,
        generatedHtmlIsCanonicalSource: false,
      },
      cleanup: "pending",
    };
  } finally {
    if (pool) await pool.end();
    await stopChild(child);
    await cluster.stop();
  }
  try {
    await fs.access(cluster.databaseDir);
    throw new Error("embedded_postgres_directory_not_removed");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  report.cleanup = "passed";
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
