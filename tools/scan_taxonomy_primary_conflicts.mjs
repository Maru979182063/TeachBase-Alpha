/** 中文说明：只读扫描候选库，报告同一题修订/标签版本的冲突，绝不自动修复。 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Pool } from 'pg';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
if (args.length !== 4 || args[0] !== '--source-data-root' || args[2] !== '--out') {
  throw new Error('required: --source-data-root PATH --out JSON');
}
const config = JSON.parse(await fs.readFile(path.join(path.resolve(args[1]), 'local.private.json'), 'utf8'));
if (config.database !== 'teachbase_candidates') throw new Error('unexpected_database');
const pool = new Pool({ host: '127.0.0.1', port: config.port, user: config.user,
  password: config.password, database: config.database, connectionTimeoutMillis: 3000 });
const client = await pool.connect();
try {
  await client.query('begin transaction isolation level repeatable read read only');
  const conflicts = (await client.query(await fs.readFile(path.join(root, 'tools/sql/scan_taxonomy_primary_conflicts.sql'), 'utf8'))).rows;
  const counts = (await client.query(`select
    (select count(*)::int from teachbase_app.question) as questions,
    (select count(*)::int from teachbase_app.question_revision) as revisions,
    (select count(*)::int from teachbase_app.question_revision where review_status='pending_review') as pending,
    (select count(*)::int from teachbase_app.question_revision where review_status='approved') as approved,
    (select count(*)::int from teachbase_app.taxonomy_version) as taxonomy_versions,
    (select count(*)::int from teachbase_app.taxonomy_node) as taxonomy_nodes,
    (select count(*)::int from teachbase_app.question_taxonomy_link) as taxonomy_links,
    (select count(*)::int from teachbase_app.question_taxonomy_link where relation_type='primary') as primary_links`)).rows[0];
  const migrations = (await client.query('select version, checksum, success from teachbase_app.flyway_schema_history where version is not null order by installed_rank')).rows;
  await client.query('commit');
  const report = { checkedAt: new Date().toISOString(), scope: 'question_revision_id + taxonomy_version_id',
    database: config.database, access: 'repeatable_read_read_only', counts, migrations, conflicts,
    conflictGroups: conflicts.length, status: conflicts.length ? 'conflicts_found' : 'no_conflicts',
    semanticLabelsValidated: false, repairedRows: 0 };
  await fs.mkdir(path.dirname(path.resolve(args[3])), { recursive: true });
  await fs.writeFile(args[3], JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ status: report.status, counts, conflictGroups: conflicts.length, out: args[3] }));
  if (conflicts.length) process.exitCode = 1;
} finally {
  await client.query('rollback').catch(() => {});
  client.release(); await pool.end();
}
