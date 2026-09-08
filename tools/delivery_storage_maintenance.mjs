/** 中文说明：离线对账和一致性备份；只报告未引用/未登记文件，不自动清理或修复业务数据。 */
import fs from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { Pool } from 'pg';

function inside(root,file){const relative=path.relative(root,file);return relative!== '..'&&!relative.startsWith('..'+path.sep)&&!path.isAbsolute(relative);}
function sorted(value){
  if(Array.isArray(value))return value.map(sorted);
  if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort((a,b)=>{const x=Array.from(a,c=>c.codePointAt(0)),y=Array.from(b,c=>c.codePointAt(0));for(let i=0;i<Math.min(x.length,y.length);i++)if(x[i]!==y[i])return x[i]-y[i];return x.length-y.length;}).map(k=>[k,sorted(value[k])]));
  return value;
}
const digest=value=>crypto.createHash('sha256').update(JSON.stringify(sorted(value))).digest('hex');
async function hashFile(file){const hash=crypto.createHash('sha256');let bytes=0;for await(const b of createReadStream(file)){bytes+=b.length;hash.update(b);}return {sha256:hash.digest('hex'),bytes};}
async function inventory(root){
  const records=[],issues=[];
  async function visit(dir){for(const entry of await fs.readdir(dir,{withFileTypes:true})){const file=path.join(dir,entry.name),key=path.relative(root,file).split(path.sep).join('/');
    if(entry.isSymbolicLink()){issues.push({code:'storage_symlink',path:key});continue;}
    if(entry.isDirectory())await visit(file);else if(entry.isFile())records.push({path:key,...await hashFile(file)});
  }}
  await visit(root);records.sort((a,b)=>a.path.localeCompare(b.path));return {records,issues};
}
export async function auditStorage(db,storageRoot){
  const root=path.resolve(storageRoot);const checkedAt=new Date().toISOString();const listing=await inventory(root);const findings=[...listing.issues];
  const versions=(await db.query('select file_version_id,workspace_id,storage_key,sha256,size_bytes,media_type from teachbase_app.file_version order by file_version_id')).rows;
  const used=new Set((await db.query(`select file_version_id::text as id from teachbase_app.source_document where file_version_id is not null
    union select file_version_id::text from teachbase_app.export_file
    union select file_version_id::text from teachbase_app.delivery_package_file where is_referenced`)).rows.map(r=>r.id));
  const questions=(await db.query('select workspace_id,provenance_json from teachbase_app.question_revision')).rows;
  for(const q of questions)for(const asset of Object.values(q.provenance_json.assetFiles||{})){
    const version=versions.find(v=>v.workspace_id===q.workspace_id&&v.sha256===asset.sha256);if(version)used.add(version.file_version_id);else findings.push({code:'question_asset_unregistered',workspaceId:q.workspace_id,sha256:asset.sha256});
  }
  const disk=new Map(listing.records.map(r=>[r.path,r]));const registeredPaths=new Set();const referenced=[],registeredUnreferenced=[];
  for(const v of versions){
    const file=path.resolve(root,v.storage_key);if(!inside(root,file)){findings.push({code:'registered_storage_escape',fileVersionId:v.file_version_id});continue;}
    const key=path.relative(root,file).split(path.sep).join('/');registeredPaths.add(key);
    const row=disk.get(key),entry={fileVersionId:v.file_version_id,workspaceId:v.workspace_id,path:key,sha256:v.sha256,sizeBytes:Number(v.size_bytes)};
    (used.has(v.file_version_id)?referenced:registeredUnreferenced).push(entry);
    if(!row)findings.push({code:'registered_file_missing',fileVersionId:v.file_version_id,path:key});
    else if(row.sha256!==v.sha256||row.bytes!==Number(v.size_bytes))findings.push({code:'registered_file_bytes_mismatch',fileVersionId:v.file_version_id,path:key});
  }
  const packages=(await db.query('select * from teachbase_app.delivery_package')).rows;
  const packageFiles=(await db.query('select * from teachbase_app.delivery_package_file')).rows;
  for(const p of packages){
    const manifest=structuredClone(p.manifest_json);delete manifest.importRequestId;
    if(digest({hashContract:'tb-delivery-v1',manifest})!==p.delivery_digest)findings.push({code:'package_digest_mismatch',packageId:p.package_id});
    const links=packageFiles.filter(f=>f.workspace_id===p.workspace_id&&f.package_id===p.package_id);
    if(links.length!==p.manifest_json.files.length)findings.push({code:'package_file_count_mismatch',packageId:p.package_id});
    for(const declared of p.manifest_json.files){const link=links.find(f=>f.file_key===declared.fileKey),version=link&&versions.find(v=>v.file_version_id===link.file_version_id&&v.workspace_id===link.workspace_id);
      if(!version||version.sha256!==declared.sha256||version.media_type!==declared.mediaType||Number(version.size_bytes)!==declared.sizeBytes||link.sha256!==declared.sha256)findings.push({code:'package_file_mapping_mismatch',packageId:p.package_id,fileKey:declared.fileKey});}
  }
  const requests=(await db.query('select * from teachbase_app.delivery_request')).rows;
  const items=(await db.query(`select i.*,q.content_hash as actual_hash,q.content_json->'deliveryContent' as actual_delivery_content,c.question_revision_id as review_revision,
    s.source_region_id as actual_region from teachbase_app.delivery_request_item i
    left join teachbase_app.question_revision q on q.question_revision_id=i.question_revision_id and q.workspace_id=i.workspace_id
    left join teachbase_app.review_case c on c.review_case_id=i.review_case_id and c.workspace_id=i.workspace_id
    left join teachbase_app.question_source_link s on s.question_revision_id=i.question_revision_id`)).rows;
  for(const r of requests){
    const owned=items.filter(i=>i.workspace_id===r.workspace_id&&i.import_request_id===r.import_request_id),receipt=r.receipt_json,p=packages.find(p=>p.workspace_id===r.workspace_id&&p.package_id===r.package_id);
    if(r.status!=='succeeded'||owned.length!==r.expected_items||receipt?.items?.length!==r.expected_items||receipt?.deliveryDigest!==r.delivery_digest||receipt?.importRequestId!==r.import_request_id||p?.delivery_digest!==r.delivery_digest)findings.push({code:'receipt_incomplete',importRequestId:r.import_request_id});
    for(const i of owned){const value=receipt?.items?.find(v=>v.itemKey===i.item_key),q=p?.manifest_json.questions.find(q=>q.itemKey===i.item_key);
      if(!value||value.questionId!==i.question_id||value.questionRevisionId!==i.question_revision_id||value.reviewCaseId!==i.review_case_id||value.sourceRegionId!==i.source_region_id||value.domainContentHash!==i.domain_content_hash||value.contentHash!==i.delivery_content_hash||i.actual_hash!==i.domain_content_hash||i.review_revision!==i.question_revision_id||i.actual_region!==i.source_region_id||!q||digest({hashContract:'tb-content-v1',content:q.content})!==i.delivery_content_hash||!i.actual_delivery_content||digest({hashContract:'tb-content-v1',content:i.actual_delivery_content})!==i.delivery_content_hash)findings.push({code:'receipt_business_mapping_mismatch',importRequestId:r.import_request_id,itemKey:i.item_key});
    }
  }
  const unregisteredDisk=listing.records.filter(r=>!registeredPaths.has(r.path));
  return {checkedAt,status:findings.length?'failed':'passed',findings,counts:{referenced:referenced.length,registeredUnreferenced:registeredUnreferenced.length,unregisteredDisk:unregisteredDisk.length,requests:requests.length,receiptItems:items.length,packages:packages.length},
    referenced,registeredUnreferenced,unregisteredDisk,inventory:listing.records,deletedFiles:0,repairedRows:0};
}
async function execute(command,args,env){const child=spawn(command,args,{env,windowsHide:true,stdio:['ignore','pipe','pipe']});const errs=[];child.stderr.on('data',b=>errs.push(b));child.stdout.resume();const code=await new Promise((resolve,reject)=>{child.once('exit',resolve);child.once('error',reject);});if(code!==0)throw new Error('backup_pg_dump_failed:'+Buffer.concat(errs).toString('utf8').slice(-1200));}
export async function backupConsistent(pool,connectionString,storageRoot,destination,{writersStopped=false}={}){
  if(!writersStopped)throw new Error('backup_requires_stopped_storage_writers');
  storageRoot=path.resolve(storageRoot);destination=path.resolve(destination);if(inside(storageRoot,destination))throw new Error('backup_destination_inside_storage');
  await fs.mkdir(destination);const started=Date.now(),client=await pool.connect();
  try{
    await client.query('begin transaction isolation level repeatable read');
    await client.query("set local lock_timeout='10s'");
    const tables=(await client.query("select tablename from pg_tables where schemaname='teachbase_app' order by tablename")).rows;
    // 名称来自 PostgreSQL catalog 并作标识符转义；锁阻止备份期间所有规范表写入。
    const quoted=tables.map(t=>'"teachbase_app"."'+t.tablename.replaceAll('"','""')+'"');
    await client.query('lock table '+quoted.join(',')+' in share mode');
    const snapshot=(await client.query('select pg_export_snapshot() as snapshot,clock_timestamp() as backup_time')).rows[0];
    const audit=await auditStorage(client,storageRoot);await fs.writeFile(path.join(destination,'source-audit.json'),JSON.stringify(audit,null,2));
    if(audit.status!=='passed')throw new Error('backup_source_inconsistent');
    const url=new URL(connectionString);const pgBin=process.env.TEACHBASE_PG_BIN||(process.platform==='win32'?'C:/Program Files/PostgreSQL/18/bin':'');
    await execute(path.join(pgBin,process.platform==='win32'?'pg_dump.exe':'pg_dump'),['-Fc','--snapshot='+snapshot.snapshot,'-f',path.join(destination,'database.dump')],{
      ...process.env,PGHOST:url.hostname,PGPORT:url.port,PGUSER:decodeURIComponent(url.username),PGPASSWORD:decodeURIComponent(url.password),PGDATABASE:url.pathname.slice(1)});
    await fs.cp(storageRoot,path.join(destination,'storage'),{recursive:true});const copied=await inventory(path.join(destination,'storage'));
    if(digest(copied.records)!==digest(audit.inventory)||copied.issues.length)throw new Error('backup_storage_changed_during_copy');
    const migrations=(await client.query('select version,checksum,success from teachbase_app.flyway_schema_history order by installed_rank')).rows;
    const receiptWatermark=(await client.query('select count(*)::int as succeeded_requests,max(completed_at) as latest_completed_at from teachbase_app.delivery_request')).rows[0];
    const manifest={backupSchemaVersion:1,snapshot:snapshot.snapshot,backupTime:snapshot.backup_time,writersStopped:true,tableLocks:'SHARE',migrations,receiptWatermark,
      dump:await hashFile(path.join(destination,'database.dump')),storageInventorySha256:digest(audit.inventory),storageFiles:audit.inventory.length,sourceCounts:audit.counts,elapsedMs:Date.now()-started,status:'complete'};
    await fs.writeFile(path.join(destination,'manifest.json'),JSON.stringify(manifest,null,2));await client.query('commit');return manifest;
  }catch(e){await client.query('rollback');await fs.writeFile(path.join(destination,'failure.json'),JSON.stringify({status:'failed',reason:e.message,elapsedMs:Date.now()-started},null,2));throw e;}
  finally{client.release();}
}
export async function restoreVerified(connectionString,storageRoot,backupRoot) {
  const start=Date.now();storageRoot=path.resolve(storageRoot);backupRoot=path.resolve(backupRoot);
  if(inside(backupRoot,storageRoot)||inside(storageRoot,backupRoot))throw new Error('restore_paths_overlap');
  const manifest=JSON.parse(await fs.readFile(path.join(backupRoot,'manifest.json'),'utf8'));
  try {await fs.access(path.join(backupRoot,'failure.json'));throw new Error('restore_backup_has_failure_marker');}catch(e){if(e.code!=='ENOENT')throw e;}
  if(manifest.backupSchemaVersion!==1||manifest.status!=='complete')throw new Error('restore_backup_not_complete');
  const dump=await hashFile(path.join(backupRoot,'database.dump')),listing=await inventory(path.join(backupRoot,'storage'));
  if(dump.sha256!==manifest.dump.sha256||dump.bytes!==manifest.dump.bytes||listing.issues.length||digest(listing.records)!==manifest.storageInventorySha256)throw new Error('restore_backup_integrity_failed');
  try {await fs.lstat(storageRoot);throw new Error('restore_storage_must_not_exist');}catch(e){if(e.code!=='ENOENT')throw e;}
  const pool=new Pool({connectionString});
  try {
    const existing=(await pool.query("select count(*)::int as n from pg_tables where schemaname not in ('pg_catalog','information_schema')")).rows[0].n;
    if(existing!==0)throw new Error('restore_database_must_be_empty');
    const url=new URL(connectionString),pgBin=process.env.TEACHBASE_PG_BIN||(process.platform==='win32'?'C:/Program Files/PostgreSQL/18/bin':'');
    await execute(path.join(pgBin,process.platform==='win32'?'pg_restore.exe':'pg_restore'),['--exit-on-error','--single-transaction','--no-owner','--no-privileges','-d',url.pathname.slice(1),path.join(backupRoot,'database.dump')],{
      ...process.env,PGHOST:url.hostname,PGPORT:url.port,PGUSER:decodeURIComponent(url.username),PGPASSWORD:decodeURIComponent(url.password)});
    await fs.cp(path.join(backupRoot,'storage'),storageRoot,{recursive:true,errorOnExist:true,force:false});const restoreMs=Date.now()-start;
    const auditStart=Date.now(),audit=await auditStorage(pool,storageRoot);
    if(audit.status!=='passed'||digest(audit.inventory)!==manifest.storageInventorySha256||JSON.stringify(audit.counts)!==JSON.stringify(manifest.sourceCounts))throw new Error('restored_consistency_failed');
    const migrations=(await pool.query('select version,checksum,success from teachbase_app.flyway_schema_history order by installed_rank')).rows;
    if(JSON.stringify(migrations)!==JSON.stringify(manifest.migrations))throw new Error('restored_migrations_mismatch');
    return {status:'passed',restoreSchemaVersion:1,restoreMs,fullAuditMs:Date.now()-auditStart,elapsedMs:Date.now()-start,counts:audit.counts,audit};
  }finally{await pool.end();}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const args=process.argv.slice(2),mode=args.shift();const options={};for(let i=0;i<args.length;i++){if(args[i]==='--writers-stopped')options.writersStopped=true;else options[args[i]]=args[++i];}
  const connection=process.env.TEACHBASE_MAINTENANCE_DATABASE_URL;if(!connection)throw new Error('TEACHBASE_MAINTENANCE_DATABASE_URL_required');
  const pool=new Pool({connectionString:connection});try{
    let result;if(mode==='audit'){const client=await pool.connect();try{await client.query('begin isolation level repeatable read read only');result=await auditStorage(client,options['--storage-root']);await client.query('commit');}finally{client.release();}}
    else if(mode==='backup')result=await backupConsistent(pool,connection,options['--storage-root'],options['--destination'],options);
    else if(mode==='restore')result=await restoreVerified(connection,options['--storage-root'],options['--backup-root']);else throw new Error('mode_must_be_audit_backup_or_restore');
    if(options['--out'])await fs.writeFile(options['--out'],JSON.stringify(result,null,2));console.log(JSON.stringify({status:result.status,counts:result.counts,elapsedMs:result.elapsedMs}));if(result.status==='failed')process.exitCode=1;
  }finally{await pool.end();}
}
