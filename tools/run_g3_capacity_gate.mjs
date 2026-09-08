/** 中文说明：合成元数据容量基线，使用隔离数据库；绝不代表真实加工质量或生产并发承诺。 */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import assert from 'node:assert/strict';
import {openContext,realManifest,endpoint,run} from '../tests/helpers/delivery_gate_context.mjs';
const args=process.argv.slice(2);assert.equal(args[0],'--source-data-root');assert.equal(args[2],'--out-dir');
const output=path.resolve(args[3]),ctx=await openContext(path.resolve(args[1]),output);
const report={startedAt:new Date().toISOString(),hardware:{platform:os.platform(),release:os.release(),cpu:os.cpus()[0].model,logicalCpus:os.cpus().length,memoryBytes:os.totalmem()},
  methodology:{population:'one synthetic content template with independent UUIDs; original 52 retained only in isolated copy',setup:'one G2 synthetic import followed by SQL metadata expansion; expansion is not G2 import throughput',query:'alternating all-match capacitytoken and no-match absentcapacityneedle',pageSize:50,samplesPerCell:36,concurrency:[1,5,10],percentiles:'nearest-rank; warm local process',limitations:'single host, duplicate-content distribution, no remote network; sample count limits tail estimates'},cells:[]};
const percentile=(values,p)=>values[Math.ceil(values.length*p)-1];
try {
  const app=await ctx.restore('g3_capacity_test');await app.start();const m=await realManifest(app,ctx.identity);m.questions=m.questions.slice(0,1);
  m.questions[0].content={contentSchemaVersion:1,titleMarkdown:'Synthetic capacity fixture',materialMarkdown:'',stemMarkdown:'capacitytoken synthetic metadata search fixture',options:[],subquestions:[],answerMarkdown:'Synthetic answer',analysisMarkdown:'Synthetic analysis',teachingNoteMarkdown:'',media:[]};
  m.questions[0].sourceEvidence={evidenceFileKeys:[],sourceBlockRefs:[],pageNumbers:[]};
  const delivered=await app.api(endpoint+'/imports','POST',m);assert.equal(delivered.status,201);const template=delivered.data.items[0];
  let populated=1;
  for(const target of [1000,10000,100000]) {
    const start=performance.now();
    await app.pool.query(`with ids as materialized (select gen_random_uuid() as qid,gen_random_uuid() as rid,g from generate_series($1::int,$2::int) g),
      new_questions as (insert into teachbase_app.question
        select (jsonb_populate_record(null::teachbase_app.question,to_jsonb(t)||jsonb_build_object('question_id',i.qid,'external_key','capacity/'||i.qid,'source_key','capacity/'||i.qid,'source_system','g3_synthetic'))).*
        from teachbase_app.question t cross join ids i where t.question_id=$3::uuid returning question_id)
      insert into teachbase_app.question_revision
        select (jsonb_populate_record(null::teachbase_app.question_revision,to_jsonb(t)||jsonb_build_object('question_revision_id',i.rid,'question_id',i.qid,'provenance_json',jsonb_build_object('capacityFixture',true)))).*
        from teachbase_app.question_revision t cross join ids i join new_questions n on n.question_id=i.qid where t.question_revision_id=$4::uuid`,[populated+1,target,template.questionId,template.questionRevisionId]);
    const setupMs=Math.round(performance.now()-start);populated=target;
    await app.pool.query('analyze teachbase_app.question;analyze teachbase_app.question_revision');
    for(const concurrency of [1,5,10]) {
      const route=i=>'/api/v1/questions/search?'+new URLSearchParams({...ctx.identity,reviewStatus:'pending_review',query:i%2?'absentcapacityneedle':'capacitytoken',limit:'50'});
      for(let i=0;i<4;i++)assert.equal((await app.api(route(i))).status,200);
      let next=0,errors=0;const times=[],started=performance.now();
      await Promise.all(Array.from({length:concurrency},async()=>{while(next<36){const index=next++,time=performance.now();try{const result=await app.api(route(index));if(result.status!==200||(index%2===0?result.data.items.length!==50:result.data.items.length!==0))errors++;}catch{errors++;}times.push(performance.now()-time);}}));
      const elapsed=performance.now()-started;times.sort((a,b)=>a-b);
      const cell={syntheticQuestions:target,totalQuestions:target+52,concurrency,requests:36,errors,setupMs,elapsedMs:Math.round(elapsed),requestsPerSecond:Math.round(36000/elapsed*100)/100,
        p50Ms:Math.round(percentile(times,.5)),p95Ms:Math.round(percentile(times,.95)),p99Ms:Math.round(percentile(times,.99)),maxMs:Math.round(times.at(-1)),nodeRssBytes:process.memoryUsage().rss};
      if(process.platform==='win32')try{cell.javaProcess=JSON.parse((await run('powershell.exe',['-NoProfile','-Command',`Get-Process -Id ${app.java.pid} | Select-Object WorkingSet64,PeakWorkingSet64,CPU | ConvertTo-Json -Compress`])).toString('utf8'));}catch{cell.javaProcessUnavailable=true;}
      cell.databaseBytes=Number((await app.pool.query('select pg_database_size(current_database()) as bytes')).rows[0].bytes);
      report.cells.push(cell);console.log(JSON.stringify(cell));
    }
  }
  report.indexes=(await app.pool.query("select indexname,indexdef from pg_indexes where schemaname='teachbase_app' and tablename in ('question','question_revision') order by indexname")).rows;
  const target=report.cells.find(c=>c.syntheticQuestions===10000&&c.concurrency===5);report.localThreshold={p95LimitMs:1000,unexpectedErrorsAllowed:0,actualP95Ms:target.p95Ms,actualErrors:target.errors,passed:target.p95Ms<=1000&&target.errors===0};
}catch(e){report.fatal=e.stack;}
finally{try{report.originalUnchanged=await ctx.close();}catch(e){report.cleanupError=e.message;}}
report.status=report.fatal||report.cleanupError||!report.localThreshold?.passed?'failed':'passed';report.finishedAt=new Date().toISOString();await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({status:report.status,fatal:report.fatal}));if(report.status!=='passed')process.exitCode=1;
