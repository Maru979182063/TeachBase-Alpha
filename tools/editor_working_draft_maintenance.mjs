import crypto from "node:crypto";
import { pathToFileURL } from "node:url";
import { Pool } from "pg";

function expectDatabaseUrl(value) {
  if (!value) throw new Error("TEACHBASE_DATABASE_URL_required");
  return value.replace(/^jdbc:/, "");
}

async function withDocumentTransaction(pool, documentId, action) {
  const client = await pool.connect();
  try {
    await client.query("begin");
    const document = await client.query(
      `select editor_document_id, workspace_id, current_revision_no, writer_mode
         from teachbase_app.editor_document
        where editor_document_id = $1
        for update`,
      [documentId],
    );
    if (!document.rowCount) throw new Error(`editor_document_not_found:${documentId}`);
    const result = await action(client, document.rows[0]);
    await client.query("commit");
    return result;
  } catch (error) {
    await client.query("rollback");
    throw error;
  } finally {
    client.release();
  }
}

async function backfillDocument(client, document) {
  if (document.writer_mode === "working_draft") return "already_working_draft";
  const legacy = await client.query(
    `select d.editor_revision_id, d.revision_no, d.updated_by, d.updated_at,
            r.schema_version, r.master_doc_json, r.version_overrides_json, r.content_hash
       from teachbase_app.editor_draft d
       join teachbase_app.editor_revision r on r.editor_revision_id = d.editor_revision_id
      where d.editor_document_id = $1 and d.workspace_id = $2`,
    [document.editor_document_id, document.workspace_id],
  );
  if (!legacy.rowCount) throw new Error(`legacy_editor_draft_missing:${document.editor_document_id}`);
  const row = legacy.rows[0];
  const content = {
    editorModel: "master-overrides-v1",
    schemaVersion: row.schema_version,
    masterDoc: row.master_doc_json,
    versionOverrides: row.version_overrides_json,
  };
  await client.query(
    `insert into teachbase_app.editor_working_draft (
       editor_document_id, workspace_id, base_revision_id, draft_version,
       content_json, content_hash, updated_by, updated_at
     ) values ($1, $2, $3, 1, $4::jsonb, $5, $6, $7)
     on conflict (editor_document_id) do update set
       base_revision_id = excluded.base_revision_id,
       draft_version = teachbase_app.editor_working_draft.draft_version + 1,
       content_json = excluded.content_json,
       content_hash = excluded.content_hash,
       updated_by = excluded.updated_by,
       updated_at = excluded.updated_at`,
    [
      document.editor_document_id,
      document.workspace_id,
      row.editor_revision_id,
      JSON.stringify(content),
      row.content_hash,
      row.updated_by,
      row.updated_at,
    ],
  );
  await client.query(
    `update teachbase_app.editor_document set writer_mode = 'working_draft'
      where editor_document_id = $1`,
    [document.editor_document_id],
  );
  return "migrated";
}

async function rollbackDocument(client, document) {
  if (document.writer_mode === "legacy") return "already_legacy";
  const draft = await client.query(
    `select content_json, content_hash, updated_by, updated_at
       from teachbase_app.editor_working_draft
      where editor_document_id = $1 and workspace_id = $2
      for update`,
    [document.editor_document_id, document.workspace_id],
  );
  if (!draft.rowCount) throw new Error(`editor_working_draft_missing:${document.editor_document_id}`);
  const row = draft.rows[0];
  let revision = await client.query(
    `select editor_revision_id, revision_no
       from teachbase_app.editor_revision
      where editor_document_id = $1 and workspace_id = $2 and content_hash = $3
      order by revision_no desc limit 1`,
    [document.editor_document_id, document.workspace_id, row.content_hash],
  );
  if (!revision.rowCount) {
    const revisionId = crypto.randomUUID();
    const revisionNo = Number(document.current_revision_no) + 1;
    const content = row.content_json;
    await client.query(
      `insert into teachbase_app.editor_revision (
         editor_revision_id, editor_document_id, workspace_id, revision_no,
         editor_model, schema_version, master_doc_json, version_overrides_json,
         content_hash, created_by, created_at
       ) values ($1, $2, $3, $4, 'master-overrides-v1', $5, $6::jsonb, $7::jsonb, $8, $9, now())`,
      [
        revisionId,
        document.editor_document_id,
        document.workspace_id,
        revisionNo,
        content.schemaVersion,
        JSON.stringify(content.masterDoc),
        JSON.stringify(content.versionOverrides),
        row.content_hash,
        row.updated_by,
      ],
    );
    await client.query(
      `update teachbase_app.editor_document set current_revision_no = $2 where editor_document_id = $1`,
      [document.editor_document_id, revisionNo],
    );
    revision = { rows: [{ editor_revision_id: revisionId, revision_no: revisionNo }], rowCount: 1 };
  }
  const frozen = revision.rows[0];
  // 先切回 legacy，随后在同一事务内移动兼容指针；数据库触发器仍会阻止顺序错误。
  await client.query(
    `update teachbase_app.editor_document
        set writer_mode = 'legacy', updated_by = $2, updated_at = now()
      where editor_document_id = $1`,
    [document.editor_document_id, row.updated_by],
  );
  await client.query(
    `insert into teachbase_app.editor_draft (
       editor_document_id, workspace_id, editor_revision_id, revision_no, updated_by, updated_at
     ) values ($1, $2, $3, $4, $5, now())
     on conflict (editor_document_id) do update set
       editor_revision_id = excluded.editor_revision_id,
       revision_no = excluded.revision_no,
       updated_by = excluded.updated_by,
       updated_at = excluded.updated_at`,
    [
      document.editor_document_id,
      document.workspace_id,
      frozen.editor_revision_id,
      frozen.revision_no,
      row.updated_by,
    ],
  );
  return "materialized_for_rollback";
}

export async function runMaintenance({ connectionString, mode, documentIds = null }) {
  if (!["backfill", "rollback-materialize"].includes(mode)) {
    throw new Error(`unsupported_maintenance_mode:${mode}`);
  }
  const pool = new Pool({ connectionString: expectDatabaseUrl(connectionString), max: 2 });
  try {
    const selected = documentIds?.length
      ? documentIds
      : (await pool.query(
          `select editor_document_id from teachbase_app.editor_document
            where writer_mode = $1 order by editor_document_id`,
          [mode === "backfill" ? "legacy" : "working_draft"],
        )).rows.map((row) => row.editor_document_id);
    const results = [];
    for (const documentId of selected) {
      const outcome = await withDocumentTransaction(pool, documentId, (client, document) =>
        mode === "backfill" ? backfillDocument(client, document) : rollbackDocument(client, document));
      results.push({ documentId, outcome });
    }
    return { schemaVersion: 1, mode, processed: results.length, results };
  } finally {
    await pool.end();
  }
}

async function main() {
  const report = await runMaintenance({
    connectionString: process.env.TEACHBASE_DATABASE_URL,
    mode: process.argv[2],
    documentIds: process.argv.slice(3),
  });
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    process.stderr.write(`${error.stack || error.message}\n`);
    process.exitCode = 1;
  });
}
