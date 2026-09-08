/** 中文说明：真实 52 题仅在隔离副本验证 G2 接收；故障夹具不进入生产代码。 */
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import http from 'node:http';
import assert from 'node:assert/strict';
import { openContext,realManifest,another,counts,endpoint,root,run } from '../tests/helpers/delivery_gate_context.mjs';

const args=process.argv.slice(2);assert.equal(args.length,4);assert.equal(args[0],'--source-data-root');assert.equal(args[2],'--out-dir');
const output=path.resolve(args[3]);const ctx=await openContext(path.resolve(args[1]),output);
const report={startedAt:new Date().toISOString(),scope:'G2_isolated_real_package',checks:[]};
async function check(name,fn){try{const evidence=await fn();report.checks.push({name,status:'passed',evidence});}catch(e){report.checks.push({name,status:'failed',error:e.message});}console.log(JSON.stringify(report.checks.at(-1)));}
try{
  const app=await ctx.restore('g2_delivery_test');await app.start();
  const m=await realManifest(app,ctx.identity);await fs.writeFile(path.join(output,'real-manifest.json'),JSON.stringify(m,null,2));
  const before=await counts(app.pool);let receipt;
  await check('real52_preflight_read_only_and_python_java_digest_parity',async()=>{
    const r=await app.api(endpoint+'/preflight','POST',m);assert.equal(r.status,200);assert.equal(r.data.eligible,true,JSON.stringify(r.data.issues));
    await fs.writeFile(path.join(output,'preflight.json'),JSON.stringify(r.data,null,2));
    assert.deepEqual(await counts(app.pool),before);
    const python=process.env.TEACHBASE_QA_PYTHON||'python';
    const expected=JSON.parse((await run(python,[path.join(root,'tools/candidate_delivery_contract.py'),path.join(output,'real-manifest.json')])).toString('utf8'));
    assert.equal(r.data.deliveryDigest,expected.requestDigest);
    return {questions:m.questions.length,warnings:r.data.warnings.length,deliveryDigest:r.data.deliveryDigest};
  });
  await check('real52_commit_success_receipt_and_business_rows',async()=>{
    const r=await app.api(endpoint+'/imports','POST',m);assert.equal(r.status,201,JSON.stringify(r.data));receipt=r.data;
    assert.equal(receipt.items.length,52);const after=await counts(app.pool);
    assert.equal(after.questions,before.questions+52);assert.equal(after.requests,1);assert.equal(after.receipt_items,52);
    const joined=(await app.pool.query(`select count(*)::int as n from teachbase_app.delivery_request_item i
      join teachbase_app.question_revision q using(question_revision_id) join teachbase_app.review_case c on c.review_case_id=i.review_case_id
      join teachbase_app.question_source_link s on s.question_revision_id=i.question_revision_id and s.source_region_id=i.source_region_id
      where q.review_status='pending_review' and c.status='open'`)).rows[0].n;
    assert.equal(joined,52);await fs.writeFile(path.join(output,'receipt.json'),JSON.stringify(receipt,null,2));
    return {after,joinedCompleteItems:joined};
  });
  await check('same_id_same_package_exact_receipt_and_no_writes',async()=>{
    const before=await counts(app.pool);const r=await app.api(endpoint+'/imports','POST',m);assert.equal(r.status,200);assert.deepEqual(r.data,receipt);assert.deepEqual(await counts(app.pool),before);
    const get=await app.api(`${endpoint}/requests/${m.importRequestId}?workspaceId=${m.workspaceId}`);assert.deepEqual(get.data,receipt);
  });
  await check('same_id_different_package_409_server_digest',async()=>{
    const changed=structuredClone(m);changed.questions[0].content.answerMarkdown+=' changed';
    const r=await app.api(endpoint+'/imports','POST',changed);assert.equal(r.status,409);assert.equal(r.data.detail,'delivery_request_conflict');
    changed.deliveryDigest=receipt.deliveryDigest;const spoof=await app.api(endpoint+'/imports','POST',changed);assert.equal(spoof.status,422);
  });
  await check('new_request_same_package_reuses_business_and_preserves_review_state',async()=>{
    const first=receipt.items[0];const approved=await app.api(`/api/v1/review-cases/${first.reviewCaseId}/decisions`,'POST',{
      ...ctx.identity,expectedContentHash:first.domainContentHash,decision:'approved',note:'isolated G2 replay fixture only',policyVersion:'g2-test-only',decisionSource:'api',evidence:{testOnly:true},evidenceOccurredAt:new Date().toISOString()});assert.equal(approved.status,200);
    const request=structuredClone(m);request.importRequestId=crypto.randomUUID();const before=await counts(app.pool);
    const r=await app.api(endpoint+'/imports','POST',request);assert.equal(r.status,201,JSON.stringify(r.data));assert.deepEqual(r.data.items,receipt.items);
    const after=await counts(app.pool);assert.equal(after.questions,before.questions);assert.equal(after.reviews,before.reviews);assert.equal(after.requests,before.requests+1);
    const changed=structuredClone(request);changed.importRequestId=crypto.randomUUID();changed.pipeline.runId='changed-in-same-package';
    const conflict=await app.api(endpoint+'/imports','POST',changed);assert.equal(conflict.status,409);assert.equal(conflict.data.detail,'delivery_package_conflict');
  });
  await check('concurrent_same_id_one_commit_identical_receipts',async()=>{
    const request=another(m);const before=await counts(app.pool);
    const rs=await Promise.all(Array.from({length:6},()=>app.api(endpoint+'/imports','POST',request)));
    assert.equal(rs.filter(r=>r.status===201).length,1);assert.equal(rs.filter(r=>r.status===200).length,5);
    for(const r of rs)assert.deepEqual(r.data,rs[0].data);const after=await counts(app.pool);
    assert.equal(after.questions,before.questions+1);assert.equal(after.requests,before.requests+1);
    return {statuses:rs.map(r=>r.status)};
  });
  await check('concurrent_same_id_different_digest_one_409',async()=>{
    const a=another(m),b=structuredClone(a);b.questions[0].content.stemMarkdown+=' alternate';
    const rs=await Promise.all([app.api(endpoint+'/imports','POST',a),app.api(endpoint+'/imports','POST',b)]);
    assert.deepEqual(rs.map(r=>r.status).sort(),[201,409]);return {statuses:rs.map(r=>r.status)};
  });
  await check('one_shot_no_cross_package_merge_even_with_same_candidate_id',async()=>{
    const n=structuredClone(m);n.packageId=crypto.randomUUID();n.importRequestId=crypto.randomUUID();n.questions=n.questions.slice(0,1);
    const r=await app.api(endpoint+'/imports','POST',n);assert.equal(r.status,201);
    assert.notEqual(r.data.items[0].questionId,receipt.items[0].questionId);assert.equal(r.data.items[0].contentHash,receipt.items[0].contentHash);
  });
  await check('preflight_then_inbox_tamper_commit_rejects_and_rolls_back',async()=>{
    const n=another(m);const bytes=Buffer.from('g2 new isolated evidence');const f={fileKey:'new-evidence',path:'new/evidence.txt',sha256:crypto.createHash('sha256').update(bytes).digest('hex'),sizeBytes:bytes.length,mediaType:'text/plain'};
    n.files.push(f);n.questions[0].sourceEvidence.evidenceFileKeys.push(f.fileKey);
    const inbox=path.join(app.storage,'inbox',n.workspaceId,n.packageId,f.path);await fs.mkdir(path.dirname(inbox),{recursive:true});await fs.writeFile(inbox,bytes);
    const p=await app.api(endpoint+'/preflight','POST',n);assert.equal(p.data.eligible,true,JSON.stringify(p.data.issues));const before=await counts(app.pool);
    await fs.writeFile(inbox,Buffer.alloc(bytes.length,120));const r=await app.api(endpoint+'/imports','POST',n);assert.equal(r.status,422);assert.deepEqual(await counts(app.pool),before);
    assert.equal((await app.api(`${endpoint}/requests/${n.importRequestId}?workspaceId=${n.workspaceId}`)).status,404);
  });
  await check('second_item_invalid_no_partial_business_or_receipt',async()=>{
    const n=another(m,2);n.questions[1].classificationSuggestions.subject=null;const before=await counts(app.pool);
    const p=await app.api(endpoint+'/preflight','POST',n);assert.equal(p.data.eligible,false);
    assert.equal((await app.api(endpoint+'/imports','POST',n)).status,422);assert.deepEqual(await counts(app.pool),before);
  });
  await check('synchronous_bounds_reject_101_items_and_oversized_file',async()=>{
    const n=another(m);n.questions=Array.from({length:101},(_,i)=>({...structuredClone(n.questions[0]),itemKey:'bounded-fixture-'+i,identity:{mode:'one_shot_candidate',candidateId:crypto.randomUUID(),stableQuestionKey:null}}));
    const before=await counts(app.pool);assert.equal((await app.api(endpoint+'/imports','POST',n)).status,422);
    n.questions=n.questions.slice(0,1);n.files[0].sizeBytes=64*1024*1024+1;const p=await app.api(endpoint+'/preflight','POST',n);
    assert.equal(p.data.eligible,false);assert.ok(p.data.issues.some(i=>i.code==='delivery_bytes_limit'));assert.deepEqual(await counts(app.pool),before);
  });
  await check('stable_source_unregistered_and_nonmember_rejected',async()=>{
    const n=another(m);n.questions[0].identity={mode:'registered_stable',stableQuestionKey:'claimed',identityContractId:'claimed',identityContractVersion:1,anchorEvidence:{recordId:'claimed'}};
    const p=await app.api(endpoint+'/preflight','POST',n);assert.equal(p.data.eligible,false);assert.ok(p.data.issues.some(i=>i.code==='stable_identity_contract_not_registered'));
    assert.equal((await app.api(endpoint+'/imports','POST',n)).status,422);
    assert.equal((await app.api(`${endpoint}/requests/${m.importRequestId}?workspaceId=${m.workspaceId}`,'GET',undefined,crypto.randomUUID())).status,403);
  });
  await check('before_commit_exception_rolls_back_all_business_and_success_receipt',async()=>{
    await app.pool.query(`create function teachbase_app.g2_fail_fixture() returns trigger language plpgsql as $$ begin raise exception 'g2_before_commit_fixture'; end $$;
      create trigger g2_fail_fixture before update on teachbase_app.delivery_request for each row when(new.status='succeeded') execute function teachbase_app.g2_fail_fixture()`);
    const n=another(m);const before=await counts(app.pool);
    try{assert.equal((await app.api(endpoint+'/imports','POST',n)).status,500);assert.deepEqual(await counts(app.pool),before);}finally{await app.pool.query('drop trigger g2_fail_fixture on teachbase_app.delivery_request;drop function teachbase_app.g2_fail_fixture()');}
    assert.equal((await app.api(endpoint+'/imports','POST',n)).status,201);
  });
  await check('database_cannot_commit_processing_or_fake_success_receipt',async()=>{
    for(const succeeded of [false,true]){
      const client=await app.pool.connect();let failure;const req=crypto.randomUUID();
      try{await client.query('begin');await client.query(`insert into teachbase_app.delivery_request(workspace_id,import_request_id,package_id,delivery_digest,status,expected_items,received_by,receipt_json,completed_at)
          values($1,$2,$3,$4,$5,1,$6,$7::jsonb,$8)`,[m.workspaceId,req,m.packageId,receipt.deliveryDigest,succeeded?'succeeded':'processing',ctx.identity.actorUserId,succeeded?JSON.stringify({importRequestId:req,deliveryDigest:receipt.deliveryDigest,items:[]}):null,succeeded?new Date():null]);
        try{await client.query('commit');}catch(e){failure=e;}assert.equal(failure?.code,'23514');assert.equal(failure?.message,'delivery_receipt_incomplete');
      }finally{await client.query('rollback').catch(()=>{});client.release();}
    }
  });
  await check('lost_response_after_success_recovers_original_receipt',async()=>{
    const n=another(m);let committed;
    const proxy=http.createServer(async(req,res)=>{try{const buffers=[];for await(const b of req)buffers.push(b);const r=await app.api(endpoint+'/imports','POST',JSON.parse(Buffer.concat(buffers).toString('utf8')));assert.equal(r.status,201);committed=r.data;res.destroy();}catch(e){res.destroy(e);}});
    await new Promise(r=>proxy.listen(0,'127.0.0.1',r));
    try{let lost=false;try{await fetch(`http://127.0.0.1:${proxy.address().port}`,{method:'POST',body:JSON.stringify(n)});}catch{lost=true;}assert.ok(lost);assert.ok(committed);
      const r=await app.api(`${endpoint}/requests/${n.importRequestId}?workspaceId=${n.workspaceId}`);assert.equal(r.status,200);assert.deepEqual(r.data,committed);
      assert.deepEqual((await app.api(endpoint+'/imports','POST',n)).data,committed);
    }finally{await new Promise(r=>proxy.close(r));}
  });
  await check('java_terminated_before_commit_rolls_back_then_same_request_retries',async()=>{
    const lock=await app.pool.connect();const lockId=1823407011;await lock.query('select pg_advisory_lock($1)',[lockId]);
    await app.pool.query(`create function teachbase_app.g2_wait_fixture() returns trigger language plpgsql as $$ begin perform pg_advisory_xact_lock(${lockId}::bigint);return new;end $$;
      create trigger g2_wait_fixture before update on teachbase_app.delivery_request for each row when(new.status='succeeded') execute function teachbase_app.g2_wait_fixture()`);
    const n=another(m);const before=await counts(app.pool);const pending=app.api(endpoint+'/imports','POST',n).catch(()=>null);
    try{
      let waiting=false;for(let i=0;i<200;i++){waiting=(await app.pool.query("select exists(select 1 from pg_locks where locktype='advisory' and objid=$1 and not granted) as waiting",[lockId])).rows[0].waiting;if(waiting)break;await new Promise(r=>setTimeout(r,50));}assert.ok(waiting,'fault_barrier_not_reached');
      assert.deepEqual(await counts(app.pool),before);await app.stop('SIGKILL');await lock.query('select pg_advisory_unlock($1)',[lockId]);await pending;
      for(let i=0;i<100;i++){const waiting=(await app.pool.query("select exists(select 1 from pg_locks where locktype='advisory' and objid=$1 and pid<>pg_backend_pid()) as waiting",[lockId])).rows[0].waiting;if(!waiting)break;await new Promise(r=>setTimeout(r,30));}
      assert.deepEqual(await counts(app.pool),before);
    }finally{await lock.query('select pg_advisory_unlock_all()');lock.release();await app.pool.query('drop trigger g2_wait_fixture on teachbase_app.delivery_request;drop function teachbase_app.g2_wait_fixture()');if(!app.java||app.java.exitCode!==null)await app.start();}
    assert.equal((await app.api(endpoint+'/imports','POST',n)).status,201);
  });
  report.finalCounts=await counts(app.pool);
}catch(e){report.fatal=e.message;}
finally{try{report.originalUnchanged=await ctx.close();}catch(e){report.cleanupError=e.message;}}
report.finishedAt=new Date().toISOString();report.status=report.fatal||report.cleanupError||report.checks.some(c=>c.status!=='passed')?'failed':'passed';await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({status:report.status,fatal:report.fatal,checks:report.checks.length}));if(report.status!=='passed')process.exitCode=1;
