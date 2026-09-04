/** 中文说明：持久化本地验证环境，数据目录由调用者指定；不连接或清理现有业务数据库。 */
import fs from 'node:fs/promises';
import { appendFileSync } from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import readline from 'node:readline';
import EmbeddedPostgres from 'embedded-postgres';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
if (args.length !== 2 || args[0] !== '--data-root') throw new Error('required: --data-root PATH');
const dataRoot = path.resolve(args[1]);
await fs.mkdir(dataRoot, { recursive: true });
const configPath = path.join(dataRoot, 'local.private.json');
let config;
try { config = JSON.parse(await fs.readFile(configPath, 'utf8')); }
catch (error) {
  if (error.code !== 'ENOENT') throw error;
  config = { database: 'teachbase_candidates', port: 15434, httpPort: 18084,
    user: 'postgres', password: crypto.randomBytes(32).toString('hex'),
    workspaceId: crypto.randomUUID(), actorUserId: crypto.randomUUID() };
  await fs.writeFile(configPath, JSON.stringify(config, null, 2), { flag: 'wx', mode: 0o600 });
}
const pg = new EmbeddedPostgres({ databaseDir: path.join(dataRoot, 'postgres'),
  user: config.user, password: config.password, port: config.port,
  authMethod: 'scram-sha-256', persistent: true, initdbFlags: ['--locale=C', '--encoding=UTF8'],
  postgresFlags: ['-c', 'listen_addresses=127.0.0.1'],
  onLog: message => appendFileSync(path.join(dataRoot, 'postgres.log'), String(message) + '\n'),
  onError: message => appendFileSync(path.join(dataRoot, 'postgres.log'), String(message) + '\n') });
try { await fs.access(path.join(dataRoot, 'postgres', 'PG_VERSION')); }
catch { await pg.initialise(); }
let java;
let client;
const baseUrl = `http://127.0.0.1:${config.httpPort}`;
async function start() {
  await pg.start();
  const admin = pg.getPgClient('postgres');
  await admin.connect();
  if (!(await admin.query('select 1 from pg_database where datname = $1', [config.database])).rowCount) {
    if (config.database !== 'teachbase_candidates') throw new Error('unexpected_local_database');
    await admin.query('create database teachbase_candidates');
  }
  await admin.end();
  java = spawn('java', ['-jar', path.join(root, 'backend/teachbase-server/target/teachbase-server-0.1.0-SNAPSHOT.jar')], {
    cwd: root, windowsHide: true,
    env: { ...process.env, TEACHBASE_DATABASE_URL: `jdbc:postgresql://127.0.0.1:${config.port}/${config.database}`,
      TEACHBASE_DATABASE_USER: config.user, TEACHBASE_DATABASE_PASSWORD: config.password,
      TEACHBASE_SERVER_PORT: String(config.httpPort), SERVER_ADDRESS: '127.0.0.1',
      TEACHBASE_STORAGE_ROOT: path.join(dataRoot, 'storage'), TEACHBASE_RENDER_ENABLED: 'false' },
    stdio: ['ignore', 'pipe', 'pipe'] });
  for (const stream of [java.stdout, java.stderr]) stream.on('data', chunk => appendFileSync(path.join(dataRoot, 'java.log'), chunk));
  let healthy = false;
  for (let attempt = 0; attempt < 150; attempt++) {
    if (java.exitCode !== null) throw new Error(`java_start_failed:${java.exitCode}; see java.log`);
    try {
      const response = await fetch(`${baseUrl}/actuator/health`, { signal: AbortSignal.timeout(1500) });
      if (response.ok && (await response.json()).status === 'UP') { healthy = true; break; }
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  if (!healthy) throw new Error('java_health_timeout; see java.log');
  client = pg.getPgClient(config.database);
  await client.connect();
  // 仅为专属本地验证库创建身份锚点；业务题目一律经 HTTP 模块端口写入。
  await client.query('begin');
  try {
    await client.query(`insert into teachbase_app.workspace (workspace_id, slug, display_name)
      values ($1, 'local-docx-candidate-validation', '本地真实题包验证') on conflict (workspace_id) do nothing`, [config.workspaceId]);
    await client.query(`insert into teachbase_app.app_user (user_id, email, display_name)
      values ($1, 'local-import@teachbase.invalid', '本地候选导入操作员') on conflict (user_id) do nothing`, [config.actorUserId]);
    await client.query(`insert into teachbase_app.workspace_member (workspace_id, user_id, member_role)
      values ($1, $2, 'owner') on conflict (workspace_id, user_id) do nothing`, [config.workspaceId, config.actorUserId]);
    await client.query('commit');
  } catch (error) { await client.query('rollback'); throw error; }
  const info = { baseUrl, database: config.database, databasePort: config.port, dataRoot,
    workspaceId: config.workspaceId, actorUserId: config.actorUserId, javaPid: java.pid,
    persistent: true, startedAt: new Date().toISOString() };
  await fs.writeFile(path.join(dataRoot, 'runtime.json'), JSON.stringify(info, null, 2));
  console.log(JSON.stringify({ status: 'ready', ...info }));
}
async function stop() {
  if (client) { await client.end(); client = null; }
  if (java && java.exitCode === null) {
    const exited = new Promise(resolve => java.once('exit', resolve));
    java.kill();
    await exited;
  }
  await pg.stop();
}
await start();
const lines = readline.createInterface({ input: process.stdin });
for await (const command of lines) {
  if (command.trim() === 'restart') { await stop(); await start(); }
  if (command.trim() === 'stop') { await stop(); process.exit(0); }
}
