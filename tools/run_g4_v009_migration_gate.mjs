import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";

import { startEmbeddedPostgresCluster } from "../tests/helpers/runtime_testkit.mjs";

const workspaceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const migrationRoot = path.join(workspaceRoot, "backend", "teachbase-server", "src", "main", "resources", "db", "migration");
const reportPath = path.join(workspaceRoot, "docs", "reports", "g4_v009_migration_gate.json");
const migrations = Array.from({ length: 9 }, (_, index) => {
  const number = String(index + 1).padStart(3, "0");
  const names = {
    "001": "foundation",
    "002": "editor_and_export_foundation",
    "003": "document_render_execution",
    "004": "question_search_and_collection_snapshots",
    "005": "question_governance_foundation",
    "006": "release_seed_loader",
    "007": "member_teaching_scope",
    "008": "editor_working_draft_separation",
    "009": "handout_content_asset_and_composition",
  };
  return `V${number}__${names[number]}.sql`;
});

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

async function apply(pool, names) {
  for (const name of names) {
    await pool.query(await fs.readFile(path.join(migrationRoot, name), "utf8"));
  }
}

async function seedV008(pool) {
  const ids = Object.fromEntries([
    "workspaceId", "userId", "fileAssetId", "fileVersionId", "sourceDocumentId", "sourceRegionId",
    "questionId", "questionRevisionId", "questionSourceLinkId", "editorDocumentId", "editorRevisionId",
  ].map((key) => [key, crypto.randomUUID()]));
  const hash = crypto.createHash("sha256").update("g4-v008-history").digest("hex");
  await pool.query("insert into teachbase_app.workspace (workspace_id,slug,display_name) values ($1,'g4-upgrade','G4 Upgrade')", [ids.workspaceId]);
  await pool.query("insert into teachbase_app.app_user (user_id,email,display_name) values ($1,'g4@example.invalid','G4')", [ids.userId]);
  await pool.query("insert into teachbase_app.workspace_member (workspace_id,user_id,member_role) values ($1,$2,'owner')", [ids.workspaceId, ids.userId]);
  await pool.query(
    `insert into teachbase_app.file_asset (file_asset_id,workspace_id,original_filename,created_by)
     values ($1,$2,'g4.docx',$3)`, [ids.fileAssetId, ids.workspaceId, ids.userId]);
  await pool.query(
    `insert into teachbase_app.file_version
       (file_version_id,file_asset_id,workspace_id,version_no,storage_provider,storage_key,media_type,size_bytes,sha256,created_by)
     values ($1,$2,$3,1,'local','tests/fixtures/g4/g4.docx','application/octet-stream',1,$4,$5)`,
    [ids.fileVersionId, ids.fileAssetId, ids.workspaceId, hash, ids.userId]);
  await pool.query(
    `insert into teachbase_app.source_document
       (source_document_id,workspace_id,file_version_id,external_source_key,source_type,status)
     values ($1,$2,$3,'g4-source','docx','ready')`,
    [ids.sourceDocumentId, ids.workspaceId, ids.fileVersionId]);
  await pool.query(
    `insert into teachbase_app.source_region
       (source_region_id,source_document_id,external_region_key,region_type,order_index)
     values ($1,$2,'B000','block',0)`, [ids.sourceRegionId, ids.sourceDocumentId]);
  await pool.query(
    `insert into teachbase_app.question
       (question_id,workspace_id,external_key,source_system,source_key,current_revision_no,created_by,updated_by)
     values ($1,$2,'g4-q','g4','q',1,$3,$3)`, [ids.questionId, ids.workspaceId, ids.userId]);
  await pool.query(
    `insert into teachbase_app.question_revision
       (question_revision_id,question_id,workspace_id,revision_no,review_status,subject,question_type,stem_markdown,
        content_json,content_hash,source_payload_hash,import_envelope_hash,created_by)
     values ($1,$2,$3,1,'unreviewed','math','single_choice','stem','{}'::jsonb,$4,$4,$4,$5)`,
    [ids.questionRevisionId, ids.questionId, ids.workspaceId, hash, ids.userId]);
  await pool.query(
    `insert into teachbase_app.question_source_link
       (question_source_link_id,question_id,question_revision_id,workspace_id,source_document_id,source_region_id)
     values ($1,$2,$3,$4,$5,$6)`,
    [ids.questionSourceLinkId, ids.questionId, ids.questionRevisionId, ids.workspaceId, ids.sourceDocumentId, ids.sourceRegionId]);
  await pool.query(
    `insert into teachbase_app.editor_document
       (editor_document_id,workspace_id,document_kind,title,current_revision_no,writer_mode,created_by,updated_by)
     values ($1,$2,'synchronized_handout','G4 History',1,'working_draft',$3,$3)`,
    [ids.editorDocumentId, ids.workspaceId, ids.userId]);
  await pool.query(
    `insert into teachbase_app.editor_revision
       (editor_revision_id,editor_document_id,workspace_id,revision_no,editor_model,schema_version,
        master_doc_json,version_overrides_json,content_hash,created_by)
     values ($1,$2,$3,1,'master-overrides-v1',1,'{"type":"doc","content":[]}'::jsonb,
       '[null,null,null]'::jsonb,$4,$5)`,
    [ids.editorRevisionId, ids.editorDocumentId, ids.workspaceId, hash, ids.userId]);
  await pool.query(
    `insert into teachbase_app.editor_working_draft
       (editor_document_id,workspace_id,base_revision_id,draft_version,content_json,content_hash,content_bytes,updated_by)
     values ($1,$2,$3,1,'{"editorModel":"master-overrides-v1","schemaVersion":1,"masterDoc":{"type":"doc","content":[]},"versionOverrides":[null,null,null]}'::jsonb,$4,1,$5)`,
    [ids.editorDocumentId, ids.workspaceId, ids.editorRevisionId, hash, ids.userId]);
  return ids;
}

async function capture(pool, ids) {
  const result = await pool.query(
    `select jsonb_build_object(
       'questionRevision',(select to_jsonb(x) from (select * from teachbase_app.question_revision where question_revision_id=$1) x),
       'editorRevision',(select to_jsonb(x) from (select * from teachbase_app.editor_revision where editor_revision_id=$2) x),
       'workingDraft',(select to_jsonb(x) from (select * from teachbase_app.editor_working_draft where editor_document_id=$3) x)
     ) value`, [ids.questionRevisionId, ids.editorRevisionId, ids.editorDocumentId]);
  return result.rows[0].value;
}

async function main() {
  const cluster = await startEmbeddedPostgresCluster("g4_v009_migration_gate");
  let fresh;
  let upgrade;
  let report;
  try {
    const freshDb = await cluster.createDatabase("g4_v009_fresh_test");
    fresh = new Pool({ connectionString: freshDb.connectionString });
    await apply(fresh, migrations);
    const version = (await fresh.query("show server_version")).rows[0].server_version;
    const tables = await fresh.query(
      `select table_name from information_schema.tables where table_schema='teachbase_app' and
       (table_name like 'standard_module%' or table_name like 'handout_%' or table_name='editor_revision_artifact_link')`,
    );
    expect(tables.rowCount === 11, `fresh_v009_table_count:${tables.rowCount}`);

    const upgradeDb = await cluster.createDatabase("g4_v009_upgrade_test");
    upgrade = new Pool({ connectionString: upgradeDb.connectionString });
    await apply(upgrade, migrations.slice(0, 8));
    const ids = await seedV008(upgrade);
    const before = await capture(upgrade, ids);
    await apply(upgrade, [migrations[8]]);
    const after = await capture(upgrade, ids);
    expect(JSON.stringify(after) === JSON.stringify(before), "v009_changed_existing_revision_or_working_draft");
    const oldLink = await upgrade.query(
      "select source_evidence_key from teachbase_app.question_source_link where question_source_link_id=$1",
      [ids.questionSourceLinkId],
    );
    expect(oldLink.rows[0].source_evidence_key === `legacy:${ids.questionSourceLinkId}`, "legacy_source_key_backfill_invalid");
    await upgrade.query(
      `insert into teachbase_app.question_source_link
         (question_source_link_id,question_id,question_revision_id,workspace_id,source_evidence_key,source_document_id,source_region_id)
       values ($1,$2,$3,$4,'second-evidence',$5,$6)`,
      [crypto.randomUUID(), ids.questionId, ids.questionRevisionId, ids.workspaceId, ids.sourceDocumentId, ids.sourceRegionId],
    );
    const links = await upgrade.query(
      "select count(*)::int count from teachbase_app.question_source_link where question_revision_id=$1",
      [ids.questionRevisionId],
    );
    expect(links.rows[0].count === 2, "question_multiple_source_evidence_not_supported");

    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      database: { engine: "PostgreSQL", version },
      migrations: { fresh: "V001->V009", upgrade: "V008->V009" },
      acceptance: {
        passed: 6,
        total: 6,
        checks: {
          freshMigrationPassed: true,
          upgradeMigrationPassed: true,
          existingRevisionAndWorkingDraftUnchanged: true,
          legacySourceEvidenceBackfilled: true,
          multipleQuestionSourceEvidenceAllowed: true,
          g4TablesPresent: true,
        },
      },
      cleanup: "pending",
    };
  } finally {
    if (fresh) await fresh.end();
    if (upgrade) await upgrade.end();
    await cluster.stop();
  }
  report.cleanup = "passed";
  await fs.mkdir(path.dirname(reportPath), { recursive: true });
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`);
  process.exit(1);
});
