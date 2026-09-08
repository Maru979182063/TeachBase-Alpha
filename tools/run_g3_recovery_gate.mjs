/** 中文说明：实际 G2 接收后停写备份，恢复到独立测试库并重新核验全部 receipt 和存储字节。 */
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { openContext,realManifest,endpoint,counts } from '../tests/helpers/delivery_gate_context.mjs';
import { auditStorage,backupConsistent,restoreVerified } from './delivery_storage_maintenance.mjs';
const args=process.argv.slice(2);assert.equal(args[0],'--source-data-root');assert.equal(args[2],'--out-dir');
const output=path.resolve(args[3]),ctx=await openContext(path.resolve(args[1]),output);
const report={startedAt:new Date().toISOString(),checks:[]};
async function check(name,fn){const evidence=await fn();report.checks.push({name,status:'passed',evidence});console.log(JSON.stringify(report.checks.at(-1)));}
try {
  const app=await ctx.restore('g3_source_test');await app.start();const m=await realManifest(app,ctx.identity);
  const bytes=Buffer.from('G3 registered but deliberately unused file');
  const f={fileKey:'unused-fixture',path:'unused.txt',sha256:crypto.createHash('sha256').update(bytes).digest('hex'),sizeBytes:bytes.length,mediaType:'text/plain'};m.files.push(f);
  const inbox=path.join(app.storage,'inbox',m.workspaceId,m.packageId);await fs.mkdir(inbox,{recursive:true});await fs.writeFile(path.join(inbox,f.path),bytes);
  await fs.writeFile(path.join(app.storage,'orphan-fixture.txt'),'G3 unregistered disk fixture');
  let receipt,audit,backup,restored;
  await check('health_separates_liveness_storage_database_and_export',async()=>{
    const ready=await app.api(endpoint+'/health');assert.equal(ready.status,200);assert.equal(ready.data.export,'DISABLED');assert.equal(ready.data.productionStableAuthorities,0);
    const hold=app.storage+'.health-fixture';await fs.rename(app.storage,hold);
    try{const down=await app.api(endpoint+'/health');assert.equal(down.status,503);assert.equal(down.data.database,'UP');assert.equal((await app.api('/actuator/health/liveness')).status,200);}finally{await fs.rename(hold,app.storage);}
    await app.pool.query('alter table teachbase_app.delivery_request rename to delivery_request_health_fixture');
    try{assert.equal((await app.api(endpoint+'/health')).status,503);assert.equal((await app.api('/actuator/health/liveness')).status,200);}finally{await app.pool.query('alter table teachbase_app.delivery_request_health_fixture rename to delivery_request');}
    assert.equal((await app.api(endpoint+'/health')).status,200);return ready.data;
  });
  await check('actual_g2_52_import_before_backup',async()=>{
    assert.equal((await app.api(endpoint+'/preflight','POST',m)).data.eligible,true);
    const started=performance.now(),result=await app.api(endpoint+'/imports','POST',m);report.real52ImportMs=Math.round(performance.now()-started);assert.equal(result.status,201,JSON.stringify(result.data));receipt=result.data;
    await fs.writeFile(path.join(output,'receipt.json'),JSON.stringify(receipt,null,2));return {...await counts(app.pool),importMs:report.real52ImportMs};
  });
  await check('transaction_result_metrics_exposed',async()=>{
    const result=await app.api('/actuator/metrics/teachbase.delivery.requests');assert.equal(result.status,200);
    assert.ok(result.data.availableTags.some(t=>t.tag==='operation'&&t.values.includes('import')));
    assert.ok(!result.data.availableTags.some(t=>t.tag.includes('Id')));return result.data;
  });
  await check('three_storage_classes_and_complete_receipt_graph',async()=>{
    audit=await auditStorage(app.pool,app.storage);assert.equal(audit.status,'passed',JSON.stringify(audit.findings));
    assert.ok(audit.counts.referenced>0&&audit.counts.registeredUnreferenced>0&&audit.counts.unregisteredDisk>0);
    await fs.writeFile(path.join(output,'before-audit.json'),JSON.stringify(audit,null,2));return audit.counts;
  });
  await check('detect_missing_and_corrupt_referenced_bytes',async()=>{
    const entry=audit.referenced[0],file=path.join(app.storage,entry.path),original=await fs.readFile(file),hold=file+'.g3-hold';
    try {await fs.rename(file,hold);const missing=await auditStorage(app.pool,app.storage);assert.ok(missing.findings.some(x=>x.code==='registered_file_missing'));
      await fs.writeFile(file,Buffer.from('corrupt'));const corrupt=await auditStorage(app.pool,app.storage);assert.ok(corrupt.findings.some(x=>x.code==='registered_file_bytes_mismatch'));
      return {missingDetected:true,corruptionDetected:true};
    }finally{await fs.writeFile(file,original);await fs.unlink(hold);}
  });
  await app.stop();
  await check('backup_requires_stopped_writers',async()=>{await assert.rejects(backupConsistent(app.pool,app.connectionString,app.storage,path.join(output,'rejected-backup')),/backup_requires_stopped_storage_writers/);});
  await check('consistent_snapshot_and_storage_backup',async()=>{
    backup=await backupConsistent(app.pool,app.connectionString,app.storage,path.join(output,'backup'),{writersStopped:true});return backup;
  });
  await check('restore_rejects_corrupt_backup_and_nonempty_database',async()=>{
    const dir=path.join(output,'backup'),file=path.join(dir,'database.dump'),original=await fs.readFile(file);
    await fs.appendFile(file,'corrupted');
    try{await assert.rejects(restoreVerified(app.connectionString,path.join(output,'rejected-restore'),dir),/restore_backup_integrity_failed/);}finally{await fs.writeFile(file,original);}
    await assert.rejects(restoreVerified(app.connectionString,path.join(output,'rejected-restore'),dir),/restore_database_must_be_empty/);
    return {corruptBackupRejected:true,nonemptyDatabaseProtected:true};
  });
  await check('restore_copy_and_full_consistency_audit',async()=>{
    let verified;restored=await ctx.restore('g3_restored_test',undefined,undefined,async(connection,storage)=>{verified=await restoreVerified(connection,storage,path.join(output,'backup'));});const copyMs=verified.restoreMs;
    const checkStart=performance.now(),result=await auditStorage(restored.pool,restored.storage),auditMs=performance.now()-checkStart;
    assert.equal(result.status,'passed',JSON.stringify(result.findings));assert.deepEqual(result.counts,audit.counts);assert.deepEqual(result.inventory,audit.inventory);
    assert.deepEqual(await counts(restored.pool),await counts(app.pool));await fs.writeFile(path.join(output,'restored-audit.json'),JSON.stringify(result,null,2));
    report.recovery={databaseAndStorageRestoreMs:Math.round(copyMs),fullAuditMs:verified.fullAuditMs,independentRepeatAuditMs:Math.round(auditMs),backupMs:backup.elapsedMs};return report.recovery;
  });
  await check('restored_receipt_get_and_exact_retry',async()=>{
    const start=performance.now();await restored.start();report.recovery.applicationReadyMs=Math.round(performance.now()-start);
    const recovered=await restored.api(`${endpoint}/requests/${m.importRequestId}?workspaceId=${m.workspaceId}`);assert.equal(recovered.status,200);assert.deepEqual(recovered.data,receipt);
    const retry=await restored.api(endpoint+'/imports','POST',m);assert.equal(retry.status,200);assert.deepEqual(retry.data,receipt);return {restoredItems:receipt.items.length,applicationReadyMs:report.recovery.applicationReadyMs};
  });
}catch(e){report.fatal=e.stack;}
finally{try{report.originalUnchanged=await ctx.close();}catch(e){report.cleanupError=e.message;}}
report.status=report.fatal||report.cleanupError?'failed':'passed';report.finishedAt=new Date().toISOString();await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({status:report.status,fatal:report.fatal}));if(report.status!=='passed')process.exitCode=1;
