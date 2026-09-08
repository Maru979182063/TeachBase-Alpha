/** 中文说明：只读真实库并创建隔离恢复副本；所有接收、故障和容量夹具只进入测试库。 */
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { Pool } from 'pg';
import { reservePort,startEmbeddedPostgresCluster } from './runtime_testkit.mjs';
export const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
export const pgBin=process.env.TEACHBASE_PG_BIN || (process.platform==='win32'?'C:/Program Files/PostgreSQL/18/bin':'');
const ext=process.platform==='win32'?'.exe':'';
export async function run(command,args,env=process.env) {
  const p=spawn(command,args,{env,windowsHide:true,stdio:['ignore','pipe','pipe']}); const out=[],err=[];
  p.stdout.on('data',b=>out.push(b));p.stderr.on('data',b=>err.push(b));
  const code=await new Promise((resolve,reject)=>{p.once('exit',resolve);p.once('error',reject);});
  assert.equal(code,0,Buffer.concat(err).toString('utf8').slice(-2000));return Buffer.concat(out);
}
export async function counts(pool) {
  return (await pool.query(`select (select count(*)::int from teachbase_app.question) as questions,
    (select count(*)::int from teachbase_app.question_revision) as revisions,
    (select count(*)::int from teachbase_app.review_case) as reviews,
    (select count(*)::int from teachbase_app.delivery_request) as requests,
    (select count(*)::int from teachbase_app.delivery_package) as packages,
    (select count(*)::int from teachbase_app.delivery_request_item) as receipt_items,
    (select count(*)::int from teachbase_app.file_version) as files,
    (select count(*)::int from teachbase_app.source_document) as source_documents,
    (select count(*)::int from teachbase_app.source_region) as regions,
    (select count(*)::int from teachbase_app.question_source_link) as source_links`)).rows[0];
}
async function fingerprint(pool) {
  const rows=[];
  for(const table of ['question','question_revision','review_case','question_taxonomy_link','file_version','source_document','source_region']) {
    const r=(await pool.query(`select md5(coalesce(string_agg(to_jsonb(t)::text,'' order by to_jsonb(t)::text),'')) as hash from teachbase_app.${table} t`)).rows[0]; rows.push([table,r.hash]);
  }
  return crypto.createHash('sha256').update(JSON.stringify(rows)).digest('hex');
}
export async function openContext(sourceRoot,output) {
  await fs.mkdir(output,{recursive:true});
  const config=JSON.parse(await fs.readFile(path.join(sourceRoot,'local.private.json'),'utf8'));
  assert.equal(config.database,'teachbase_candidates');
  const original=new Pool({host:'127.0.0.1',port:config.port,user:config.user,password:config.password,database:config.database,connectionTimeoutMillis:3000});
  const before=await fingerprint(original);
  const dump=path.join(output,'source.dump');
  await run(path.join(pgBin,'pg_dump'+ext),['-h','127.0.0.1','-p',String(config.port),'-U',config.user,'-d',config.database,'-Fc','-f',dump],{...process.env,PGPASSWORD:config.password});
  const cluster=await startEmbeddedPostgresCluster('delivery_stage_test');
  const context={output,original,cluster,before,identity:{workspaceId:config.workspaceId,actorUserId:config.actorUserId},instances:[]};
  context.restore=async(name,from=dump,storageFrom=path.join(sourceRoot,'storage'))=>{
    const db=await cluster.createDatabase(name);const url=new URL(db.connectionString);
    await run(path.join(pgBin,'pg_restore'+ext),['-h','127.0.0.1','-p',String(cluster.port),'-U',decodeURIComponent(url.username),'-d',db.database,'--no-owner','--no-privileges',from],{...process.env,PGPASSWORD:decodeURIComponent(url.password)});
    const storage=path.join(output,name,'storage');await fs.cp(storageFrom,storage,{recursive:true});
    const instance={...db,url,storage,pool:new Pool({connectionString:db.connectionString}),java:null,logs:[],port:await reservePort()}; instance.baseUrl=`http://127.0.0.1:${instance.port}`;
    instance.start=async()=>{
      instance.java=spawn('java',['-jar',path.join(root,'backend/teachbase-server/target/teachbase-server-0.1.0-SNAPSHOT.jar')],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe'],env:{...process.env,
        TEACHBASE_DATABASE_URL:`jdbc:postgresql://127.0.0.1:${cluster.port}/${db.database}`,TEACHBASE_DATABASE_USER:decodeURIComponent(url.username),TEACHBASE_DATABASE_PASSWORD:decodeURIComponent(url.password),
        TEACHBASE_SERVER_PORT:String(instance.port),SERVER_ADDRESS:'127.0.0.1',TEACHBASE_STORAGE_ROOT:storage,TEACHBASE_RENDER_ENABLED:'false'}});
      for(const stream of [instance.java.stdout,instance.java.stderr]) stream.on('data',b=>instance.logs.push(b));
      for(let i=0;i<180;i++) {
        if(instance.java.exitCode!==null||instance.java.signalCode!==null) throw new Error('java_exited:'+Buffer.concat(instance.logs).toString('utf8').slice(-3000));
        try {if((await fetch(instance.baseUrl+'/actuator/health',{signal:AbortSignal.timeout(1000)})).ok)return;}catch{}
        await new Promise(r=>setTimeout(r,250));
      }
      throw new Error('java_health_timeout');
    };
    instance.stop=async(signal='SIGTERM')=>{if(instance.java&&instance.java.exitCode===null&&instance.java.signalCode===null){const stopped=new Promise(r=>instance.java.once('exit',r));instance.java.kill(signal);await stopped;} instance.java=null; await fs.writeFile(path.join(output,name,'java.log'),Buffer.concat(instance.logs));};
    instance.api=async(route,method='GET',body,actor=context.identity.actorUserId)=>{
      const response=await fetch(instance.baseUrl+route,{method,headers:{'Content-Type':'application/json','X-Actor-Id':actor},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(150000)});
      return {status:response.status,data:await response.json()};
    };
    context.instances.push(instance); return instance;
  };
  context.close=async()=>{
    for(const instance of context.instances){await instance.stop();await instance.pool.end();}
    await cluster.stop();const unchanged=await fingerprint(original)===before;await original.end();assert.ok(unchanged,'original_database_changed');return unchanged;
  };
  return context;
}
export const endpoint='/api/v1/ingestion/deliveries/v1';
export async function realManifest(instance,identity) {
  const fileRows=(await instance.pool.query('select * from teachbase_app.file_version where workspace_id=$1 order by file_version_id',[identity.workspaceId])).rows;
  const docs=(await instance.pool.query('select * from teachbase_app.source_document where workspace_id=$1 order by source_document_id',[identity.workspaceId])).rows;
  const rows=(await instance.pool.query('select * from teachbase_app.question_revision where workspace_id=$1 order by question_revision_id',[identity.workspaceId])).rows;
  assert.equal(rows.length,52);assert.equal(docs.length,1);
  const fileKey=f=>'file-'+f.file_version_id;
  const documentFile=fileRows.find(f=>f.file_version_id===docs[0].file_version_id);assert.ok(documentFile);
  const evidenceKeys=fileRows.filter(f=>!f.media_type.startsWith('image/')).map(fileKey);
  const m={manifestSchemaVersion:1,importRequestId:crypto.randomUUID(),packageId:crypto.randomUUID(),workspaceId:identity.workspaceId,sourceSystem:'doc_math',pipeline:{runId:'g2-isolated-52',profileVersion:'existing-final-packets-20260904'},
    files:fileRows.map(f=>({fileKey:fileKey(f),path:f.storage_key,sha256:f.sha256,sizeBytes:Number(f.size_bytes),mediaType:f.media_type})),
    sourceDocuments:[{documentKey:'original-document',fileKey:fileKey(documentFile),documentStableKey:null}],questions:[]};
  for(const r of rows){
    const legacy=r.content_json;const assets=r.provenance_json.assetFiles||{};
    const c={contentSchemaVersion:1,titleMarkdown:r.title,materialMarkdown:r.material_markdown,stemMarkdown:r.stem_markdown,
      options:r.options_json.map(o=>({label:o.label,markdown:o.markdown??o.text??o.content})),subquestions:(legacy.subquestions||[]).map(s=>s.markdown),answerMarkdown:r.answer_markdown,analysisMarkdown:r.analysis_markdown,teachingNoteMarkdown:legacy.teaching_note_md||'',media:[]};
    const used=new Set([...JSON.stringify(c).matchAll(/asset:\/\/([^\s)"'<>]+)/g)].map(x=>x[1]));
    for(const key of [...used].sort()){const a=assets[key];assert.ok(a,'legacy_asset_missing:'+key);const file=fileRows.find(f=>f.sha256===a.sha256);assert.ok(file);c.media.push({assetKey:key,sha256:file.sha256,mediaType:file.media_type});}
    m.questions.push({itemKey:'legacy-'+r.question_revision_id,identity:{mode:'one_shot_candidate',candidateId:crypto.randomUUID(),stableQuestionKey:null},sourceDocumentKey:'original-document',sourceEvidence:{evidenceFileKeys:evidenceKeys,sourceBlockRefs:[],pageNumbers:[]},content:c,contentHash:null,
      classificationSuggestions:{subject:r.subject,stage:r.stage||null,grade:r.grade||null,questionType:r.question_type,difficultyStars:r.difficulty_stars,tags:[]}});
  }
  return m;
}
export function another(m,n=1){const x=structuredClone(m);x.importRequestId=crypto.randomUUID();x.packageId=crypto.randomUUID();x.questions=x.questions.slice(0,n);for(const q of x.questions)q.identity.candidateId=crypto.randomUUID();return x;}
