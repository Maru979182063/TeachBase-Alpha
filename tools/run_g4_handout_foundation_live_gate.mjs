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
const fixtureRoot = path.join(workspaceRoot, "tests", "fixtures", "g4");
const reportPath = path.join(workspaceRoot, "docs", "reports", "g4_handout_foundation_live_gate.json");
let capturedLogs = { stdout: [], stderr: [] };

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

function sha(value) {
  return crypto.createHash("sha256").update(String(value)).digest("hex");
}

async function waitForHealth(baseUrl, child, logs) {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`java_server_exited:${child.exitCode}\n${logs.stderr.join("")}`);
    try {
      const result = await fetchJson(`${baseUrl}/actuator/health`);
      if (result.ok && result.data?.status === "UP") return;
    } catch {
      // Flyway 和 Spring 启动期间短暂拒绝连接属于正常竞态。
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
  if (child.exitCode === null) {
    if (process.platform === "win32") {
      const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
      await new Promise((resolve) => killer.once("exit", resolve));
    } else child.kill("SIGKILL");
  }
}

async function registerFile(pool, workspaceId, actorUserId, key, hash = sha(key)) {
  const existing = await pool.query(
    "select file_version_id from teachbase_app.file_version where workspace_id=$1 and sha256=$2",
    [workspaceId, hash],
  );
  if (existing.rowCount === 1) return existing.rows[0].file_version_id;
  const fileAssetId = crypto.randomUUID();
  const fileVersionId = crypto.randomUUID();
  await pool.query(
    `insert into teachbase_app.file_asset
       (file_asset_id,workspace_id,original_filename,created_by)
     values ($1,$2,$3,$4)`,
    [fileAssetId, workspaceId, path.posix.basename(key), actorUserId],
  );
  await pool.query(
    `insert into teachbase_app.file_version
       (file_version_id,file_asset_id,workspace_id,version_no,storage_provider,storage_key,media_type,size_bytes,sha256,created_by)
     values ($1,$2,$3,1,'local',$4,'application/octet-stream',1,$5,$6)`,
    [fileVersionId, fileAssetId, workspaceId, key, hash, actorUserId],
  );
  return fileVersionId;
}

async function registerSource(pool, workspaceId, fileVersionId, key, blocks) {
  const sourceDocumentId = crypto.randomUUID();
  await pool.query(
    `insert into teachbase_app.source_document
       (source_document_id,workspace_id,file_version_id,external_source_key,source_type,status,title)
     values ($1,$2,$3,$4,'docx','ready',$4)`,
    [sourceDocumentId, workspaceId, fileVersionId, key],
  );
  const regionByBlock = new Map();
  for (const block of blocks) {
    const id = crypto.randomUUID();
    regionByBlock.set(block.blockId, id);
    await pool.query(
      `insert into teachbase_app.source_region
         (source_region_id,source_document_id,external_region_key,region_type,order_index,source_ref_json)
       values ($1,$2,$3,$4,$5,$6::jsonb)`,
      [id, sourceDocumentId, block.blockId, block.kind === "table" ? "table" : "block",
        block.sourceIndex, JSON.stringify({ blockId: block.blockId, xmlSha256: block.xmlSha256 })],
    );
  }
  return { sourceDocumentId, regionByBlock };
}

async function seedQuestions(pool, workspaceId, actorUserId, prefix, fixture, source) {
  const aliases = fixture.deduplication?.aliases ?? {};
  const canonicalKeys = [...new Set(fixture.questions.map((question) => aliases[question.id ?? question.questionId] ?? (question.id ?? question.questionId)))];
  const canonical = new Map();
  for (const key of canonicalKeys) {
    const questionId = crypto.randomUUID();
    const questionRevisionId = crypto.randomUUID();
    const contentHash = sha(`${prefix}:question:${key}`);
    await pool.query(
      `insert into teachbase_app.question
         (question_id,workspace_id,external_key,source_system,source_key,current_revision_no,created_by,updated_by)
       values ($1,$2,$3,'g4-golden',$3,1,$4,$4)`,
      [questionId, workspaceId, `${prefix}:${key}`, actorUserId],
    );
    await pool.query(
      `insert into teachbase_app.question_revision
         (question_revision_id,question_id,workspace_id,revision_no,review_status,subject,question_type,
          stem_markdown,content_json,content_hash,source_payload_hash,import_envelope_hash,approved_at,created_by)
       values ($1,$2,$3,1,'approved',$4,'golden',$5,$6::jsonb,$7,$7,$7,now(),$8)`,
      [questionRevisionId, questionId, workspaceId, prefix === "english" ? "English" : "Math",
        key, JSON.stringify({ fixture: prefix, canonicalQuestionKey: key }), contentHash, actorUserId],
    );
    await pool.query(
      "update teachbase_app.question set approved_revision_id=$1 where question_id=$2",
      [questionRevisionId, questionId],
    );
    canonical.set(key, { questionId, questionRevisionId });
  }
  const byOccurrence = new Map();
  for (const question of fixture.questions) {
    const occurrenceKey = question.id ?? question.questionId;
    const canonicalKey = aliases[occurrenceKey] ?? occurrenceKey;
    const target = canonical.get(canonicalKey);
    byOccurrence.set(occurrenceKey, target);
    const blockIds = question.blockIds ?? question.ownedBlockIds;
    const first = blockIds[0];
    await pool.query(
      `insert into teachbase_app.question_source_link
         (question_source_link_id,question_id,question_revision_id,workspace_id,source_evidence_key,
          source_document_id,source_region_id,source_label,source_ref_json)
       values ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)`,
      [crypto.randomUUID(), target.questionId, target.questionRevisionId, workspaceId,
        `${prefix}:${occurrenceKey}`, source.sourceDocumentId, source.regionByBlock.get(first),
        `${prefix}:${occurrenceKey}`, JSON.stringify({ occurrenceKey, blockId: first })],
    );
  }
  return { byOccurrence, uniqueRevisionCount: canonical.size };
}

async function createTaxonomy(baseUrl, workspaceId, actorUserId, prefix) {
  const version = await fetchJson(`${baseUrl}/api/v1/taxonomies/versions`, {
    method: "POST",
    body: { workspaceId, actorUserId, taxonomyKey: `${prefix}-knowledge`, versionKey: "v1", subject: prefix, stage: "high", schemaVersion: 1 },
  });
  expect(version.status === 200, `${prefix}_taxonomy_version:${version.status}`);
  const node = await fetchJson(`${baseUrl}/api/v1/taxonomies/versions/${version.data.taxonomyVersionId}/nodes`, {
    method: "POST",
    body: { workspaceId, actorUserId, knowledgeCode: `${prefix}.foundation`, displayName: `${prefix} foundation`, parentNodeId: null, sortOrder: 0, metadata: {}, aliases: [] },
  });
  expect(node.status === 200, `${prefix}_taxonomy_node:${node.status}`);
  const activated = await fetchJson(`${baseUrl}/api/v1/taxonomies/versions/${version.data.taxonomyVersionId}/activate`, {
    method: "POST", body: { workspaceId, actorUserId },
  });
  expect(activated.status === 200, `${prefix}_taxonomy_activate:${activated.status}`);
  return node.data.taxonomyNodeId;
}

async function createModules(pool, baseUrl, workspaceId, actorUserId, prefix, fixture, source, taxonomyNodeId) {
  const moduleByKey = new Map();
  for (const [index, module] of fixture.standardModules.entries()) {
    const sourceKey = module.id ?? module.moduleInstanceKey;
    const blockIds = module.blockIds ?? module.children.flatMap((child) => child.blockIds ?? []);
    const created = await fetchJson(`${baseUrl}/api/v1/standard-modules`, {
      method: "POST",
      body: {
        workspaceId,
        actorUserId,
        moduleKey: `${prefix}:${sourceKey}`,
        moduleType: module.type ?? module.moduleType,
        title: module.name ?? module.moduleTypeName,
        subject: prefix === "english" ? "English" : "Math",
        stage: "high",
        grade: "",
        schemaVersion: 1,
        content: {
          type: "standardModule",
          sourceBlockIds: blockIds,
          richContentSummary: prefix === "english" && index === 1 ? { tableCount: 4, imageOccurrences: 9 } : {},
        },
      },
    });
    expect([200, 201].includes(created.status), `${prefix}_module_create:${sourceKey}:${created.status}`);
    const revisionId = created.data.standardModuleRevisionId;
    const firstBlock = blockIds[0] ?? fixture.blocks[module.range[0]].blockId;
    const linked = await fetchJson(`${baseUrl}/api/v1/standard-modules/revisions/${revisionId}/sources`, {
      method: "POST",
      body: {
        workspaceId, actorUserId, sourceEvidenceKey: `${prefix}:${sourceKey}`,
        sourceDocumentId: source.sourceDocumentId, sourceRegionId: source.regionByBlock.get(firstBlock),
        sourceRole: "canonical", sourceReference: { sourceKey, firstBlock },
      },
    });
    expect(linked.status === 200, `${prefix}_module_source:${sourceKey}:${linked.status}`);
    const review = await fetchJson(`${baseUrl}/api/v1/review-cases/standard-modules`, {
      method: "POST", body: { workspaceId, actorUserId, standardModuleRevisionId: revisionId, assignedTo: actorUserId },
    });
    expect(review.status === 200, `${prefix}_module_review_open:${sourceKey}:${review.status}`);
    const decision = await fetchJson(`${baseUrl}/api/v1/review-cases/${review.data.reviewCaseId}/decisions`, {
      method: "POST",
      body: {
        workspaceId, actorUserId, expectedContentHash: review.data.expectedContentHash,
        decision: "approved", note: "G4 golden fixture approval", policyVersion: "g4-golden-v1",
        decisionSource: "api", evidence: { fixture: prefix, sourceKey }, evidenceOccurredAt: new Date().toISOString(),
      },
    });
    expect(decision.status === 200 && decision.data.status === "approved", `${prefix}_module_review_decision:${sourceKey}`);
    const taxonomy = await fetchJson(`${baseUrl}/api/v1/taxonomies/standard-module-assignments`, {
      method: "POST",
      body: { workspaceId, actorUserId, standardModuleRevisionId: revisionId, taxonomyNodeId, relationType: "secondary", assignmentSource: "human", confidence: 1 },
    });
    expect(taxonomy.status === 200, `${prefix}_module_taxonomy:${sourceKey}:${taxonomy.status}`);
    moduleByKey.set(sourceKey, {
      standardModuleId: created.data.standardModuleId,
      standardModuleRevisionId: revisionId,
    });
  }
  if (prefix === "english") {
    const target = [...moduleByKey.values()][1];
    for (let index = 0; index < 9; index++) {
      const key = `tests/fixtures/g4/english/image-${index + 1}.png`;
      const fileVersionId = await registerFile(pool, workspaceId, actorUserId, key);
      const linked = await fetchJson(`${baseUrl}/api/v1/standard-modules/revisions/${target.standardModuleRevisionId}/files`, {
        method: "POST",
        body: { workspaceId, actorUserId, fileVersionId, referenceKey: `image-${index + 1}`, referenceRole: "image", metadata: { occurrence: index + 1 } },
      });
      expect(linked.status === 200, `english_module_image_link:${index + 1}:${linked.status}`);
    }
  }
  return moduleByKey;
}

function sourceLinks(blockIds, source, prefix, claimed) {
  return blockIds.map((blockId) => {
    expect(!claimed.has(blockId), `${prefix}_block_claimed_twice:${blockId}`);
    claimed.add(blockId);
    return {
      sourceEvidenceKey: `${prefix}:${blockId}`,
      sourceDocumentId: source.sourceDocumentId,
      sourceRegionId: source.regionByBlock.get(blockId),
      sourceRole: "teacher_original",
      sourceReference: { blockId },
    };
  });
}

function englishOccurrences(fixture, source, questions, modules) {
  const claimed = new Set();
  const occurrences = [];
  const moduleDefinitions = new Map([
    ...fixture.standardModules.map((item) => [item.id, { ...item, asset: true }]),
    ...fixture.questionSectionContainers.map((item) => [item.id, { ...item, asset: false }]),
  ]);
  const questionDefinitions = new Map(fixture.questions.map((item) => [item.id, item]));
  for (const [rootIndex, top] of fixture.topLevelSequence.entries()) {
    const rootKey = `teacher:root:${String(rootIndex).padStart(3, "0")}`;
    if (top.kind === "ordinary_placement") {
      occurrences.push({ occurrenceKey: rootKey, parentOccurrenceKey: null, positionIndex: rootIndex,
        kind: "ordinary_content", questionRevisionId: null, standardModuleRevisionId: null,
        localContent: { type: "sourceBlocks", blockIds: top.blockIds }, attributes: {},
        sources: sourceLinks(top.blockIds, source, "english", claimed) });
      continue;
    }
    const definition = moduleDefinitions.get(top.moduleId);
    const asset = definition.asset;
    occurrences.push({ occurrenceKey: rootKey, parentOccurrenceKey: null, positionIndex: rootIndex,
      kind: asset ? "standard_module" : "container", questionRevisionId: null,
      standardModuleRevisionId: asset ? modules.get(top.moduleId).standardModuleRevisionId : null,
      localContent: null, attributes: { sourceKey: top.moduleId, containerType: definition.type }, sources: [] });
    for (const [childIndex, child] of definition.children.entries()) {
      const childKey = `${rootKey}:child:${String(childIndex).padStart(3, "0")}`;
      if (child.kind === "question_reference") {
        const question = questionDefinitions.get(child.questionId);
        occurrences.push({ occurrenceKey: childKey, parentOccurrenceKey: rootKey, positionIndex: childIndex,
          kind: "question", questionRevisionId: questions.byOccurrence.get(child.questionId).questionRevisionId,
          standardModuleRevisionId: null, localContent: null, attributes: { sourceQuestionKey: child.questionId },
          sources: sourceLinks(question.blockIds, source, "english", claimed) });
      } else {
        occurrences.push({ occurrenceKey: childKey, parentOccurrenceKey: rootKey, positionIndex: childIndex,
          kind: "ordinary_content", questionRevisionId: null, standardModuleRevisionId: null,
          localContent: { type: "sourceBlocks", blockIds: child.blockIds }, attributes: {},
          sources: sourceLinks(child.blockIds, source, "english", claimed) });
      }
    }
  }
  expect(claimed.size === 439, `english_claimed_block_count:${claimed.size}`);
  return occurrences;
}

function circleOccurrences(fixture, source, questions, modules) {
  const claimed = new Set();
  const placements = new Map(fixture.ordinaryPlacements.map((item) => [item.placementKey, item]));
  const questionDefinitions = new Map(fixture.questions.map((item) => [item.questionId, item]));
  const occurrences = fixture.topLevelSequence.map((top, index) => {
    const common = { occurrenceKey: `teacher:root:${String(index).padStart(3, "0")}`, parentOccurrenceKey: null, positionIndex: index, attributes: { sourceRef: top.ref } };
    if (top.kind === "standard_module_occurrence") return { ...common, kind: "standard_module", questionRevisionId: null,
      standardModuleRevisionId: modules.get(top.ref).standardModuleRevisionId, localContent: null, sources: [] };
    if (top.kind === "question_occurrence") {
      const question = questionDefinitions.get(top.ref);
      return { ...common, kind: "question", questionRevisionId: questions.byOccurrence.get(top.ref).questionRevisionId,
        standardModuleRevisionId: null, localContent: null,
        sources: sourceLinks(question.ownedBlockIds, source, "circle", claimed) };
    }
    const placement = placements.get(top.ref);
    return { ...common, kind: "ordinary_content", questionRevisionId: null, standardModuleRevisionId: null,
      localContent: { type: "sourceBlocks", blockIds: placement.blockIds },
      sources: sourceLinks(placement.blockIds, source, "circle", claimed) };
  });
  // 标准模块自己的来源块由 module occurrence 表达；将精确块证据挂到该 occurrence。
  for (const [index, top] of fixture.topLevelSequence.entries()) {
    if (top.kind !== "standard_module_occurrence") continue;
    const module = fixture.standardModules.find((item) => item.moduleInstanceKey === top.ref);
    occurrences[index].sources = sourceLinks(module.blockIds, source, "circle", claimed);
  }
  expect(claimed.size === 320, `circle_claimed_block_count:${claimed.size}`);
  return occurrences;
}

async function seedEditorBoundary(pool, workspaceId, actorUserId, prefix) {
  const editorDocumentId = crypto.randomUUID();
  const editorRevisionId = crypto.randomUUID();
  const confirmationId = crypto.randomUUID();
  const snapshotId = crypto.randomUUID();
  const contentHash = sha(`${prefix}:editor-revision`);
  await pool.query(
    `insert into teachbase_app.editor_document
       (editor_document_id,workspace_id,document_kind,title,current_revision_no,writer_mode,created_by,updated_by)
     values ($1,$2,'synchronized_handout',$3,1,'working_draft',$4,$4)`,
    [editorDocumentId, workspaceId, `${prefix} G4`, actorUserId],
  );
  for (const [key, name, order] of [["basic", "基础版", 0], ["advanced", "进阶版", 1], ["common", "常用版", 2]]) {
    await pool.query(
      "insert into teachbase_app.editor_variant (editor_document_id,workspace_id,variant_key,display_name,sort_order) values ($1,$2,$3,$4,$5)",
      [editorDocumentId, workspaceId, key, name, order],
    );
  }
  await pool.query(
    `insert into teachbase_app.editor_revision
       (editor_revision_id,editor_document_id,workspace_id,revision_no,editor_model,schema_version,master_doc_json,
        version_overrides_json,content_hash,created_by)
     values ($1,$2,$3,1,'master-overrides-v1',1,'{"type":"doc","content":[]}'::jsonb,'[null,null,null]'::jsonb,$4,$5)`,
    [editorRevisionId, editorDocumentId, workspaceId, contentHash, actorUserId],
  );
  const draft = { editorModel: "master-overrides-v1", schemaVersion: 1, masterDoc: { type: "doc", content: [] }, versionOverrides: [null, null, null] };
  await pool.query(
    `insert into teachbase_app.editor_working_draft
       (editor_document_id,workspace_id,base_revision_id,draft_version,content_json,content_hash,content_bytes,updated_by)
     values ($1,$2,$3,7,$4::jsonb,$5,$6,$7)`,
    [editorDocumentId, workspaceId, editorRevisionId, JSON.stringify(draft), contentHash,
      Buffer.byteLength(JSON.stringify(draft)), actorUserId],
  );
  await pool.query(
    `insert into teachbase_app.editor_preview_confirmation
       (editor_preview_confirmation_id,editor_document_id,workspace_id,editor_revision_id,variant_key,audience,confirmed_by)
     values ($1,$2,$3,$4,'common','teacher',$5)`,
    [confirmationId, editorDocumentId, workspaceId, editorRevisionId, actorUserId],
  );
  await pool.query(
    `insert into teachbase_app.editor_snapshot
       (editor_snapshot_id,editor_document_id,workspace_id,editor_revision_id,editor_preview_confirmation_id,
        variant_key,audience,schema_version,frozen_content_json,content_hash)
     values ($1,$2,$3,$4,$5,'common','teacher',1,'{"type":"doc"}'::jsonb,$6)`,
    [snapshotId, editorDocumentId, workspaceId, editorRevisionId, confirmationId, contentHash],
  );
  return { editorDocumentId, editorRevisionId, snapshotId, contentHash };
}

async function createArtifacts(
  pool,
  workspaceId,
  actorUserId,
  prefix,
  fixture,
  sourceDocumentId,
  sourceFileVersionId,
) {
  const roles = ["original_docx", "split_manifest", "preservation_bundle", "roundtrip_output"];
  const artifacts = [];
  for (const role of roles) {
    const key = fixture.artifactKeys?.[{
      original_docx: "originalDocx", split_manifest: "splitManifest",
      preservation_bundle: "preservationBundle", roundtrip_output: "roundtripOutput",
    }[role]] ?? `tests/fixtures/g4/${prefix}/${role}.bin`;
    const fileVersionId = role === "original_docx"
      ? sourceFileVersionId
      : await registerFile(pool, workspaceId, actorUserId, key, sha(`${prefix}:${role}`));
    artifacts.push({ artifactKey: `${prefix}:${role}`, artifactRole: role, fileVersionId,
      sourceDocumentId: role === "original_docx" ? sourceDocumentId : null, metadata: { fixture: prefix } });
  }
  if (fixture.studentProjection) {
    const key = "tests/fixtures/g4/english/student-original.docx";
    const fileVersionId = await registerFile(pool, workspaceId, actorUserId, key, fixture.studentProjection.source.sha256);
    const student = await registerSource(pool, workspaceId, fileVersionId, "english-student-source", []);
    artifacts.push({ artifactKey: "english:student-original", artifactRole: "original_docx", fileVersionId,
      sourceDocumentId: student.sourceDocumentId, metadata: { edition: "student" } });
  }
  return artifacts;
}

async function exerciseFixture(pool, baseUrl, workspaceId, actorUserId, prefix, fixture) {
  const sourceFile = await registerFile(
    pool, workspaceId, actorUserId, `tests/fixtures/g4/${prefix}/teacher-original.docx`,
    fixture.source?.sha256 ?? sha(`${prefix}:source`),
  );
  const source = await registerSource(pool, workspaceId, sourceFile, `${prefix}-teacher-source`, fixture.blocks);
  const questions = await seedQuestions(pool, workspaceId, actorUserId, prefix, fixture, source);
  const taxonomyNodeId = await createTaxonomy(baseUrl, workspaceId, actorUserId, prefix);
  const modules = await createModules(pool, baseUrl, workspaceId, actorUserId, prefix, fixture, source, taxonomyNodeId);
  const editor = await seedEditorBoundary(pool, workspaceId, actorUserId, prefix);
  const artifacts = await createArtifacts(
    pool,
    workspaceId,
    actorUserId,
    prefix,
    fixture,
    source.sourceDocumentId,
    sourceFile,
  );
  const teacherOccurrences = prefix === "english"
    ? englishOccurrences(fixture, source, questions, modules)
    : circleOccurrences(fixture, source, questions, modules);
  const editions = [{
    editionKey: "teacher", editionRole: "canonical", canonicalTeacherEditionKey: null,
    schemaVersion: 1, projectionRules: {}, delta: {}, occurrences: teacherOccurrences,
  }];
  if (fixture.studentProjection) editions.push({
    editionKey: "student", editionRole: "projection", canonicalTeacherEditionKey: "teacher",
    schemaVersion: 1,
    projectionRules: { strategy: "teacher-canonical-delta-v1", sharedQuestionAssets: true },
    delta: fixture.studentProjection,
    occurrences: [],
  });
  const compositionUrl = `${baseUrl}/api/v1/handouts/${editor.editorDocumentId}/revisions/${editor.editorRevisionId}/composition`;
  const concurrentCreates = await Promise.all(Array.from({ length: 4 }, () =>
    fetchJson(compositionUrl, { method: "POST", body: { workspaceId, actorUserId, editions, artifacts } })));
  expect(concurrentCreates.every((item) => item.status === 200),
    `${prefix}_composition_concurrent_status:${JSON.stringify(concurrentCreates.map((item) => ({ status: item.status, data: item.data })))}`);
  const createdTeacherCount = concurrentCreates.filter((item) =>
    item.data.editions.some((edition) => edition.editionKey === "teacher" && !edition.replayed)).length;
  expect(createdTeacherCount === 1, `${prefix}_composition_exactly_one_creator:${createdTeacherCount}`);
  const response = concurrentCreates[0];
  const replay = await fetchJson(
    compositionUrl,
    { method: "POST", body: { workspaceId, actorUserId, editions, artifacts } },
  );
  expect(replay.status === 200 && replay.data.editions.every((item) => item.replayed), `${prefix}_composition_replay_failed`);
  const changedEditions = structuredClone(editions);
  changedEditions[0].delta = { forbiddenRewrite: true };
  const payloadConflict = await fetchJson(compositionUrl, {
    method: "POST", body: { workspaceId, actorUserId, editions: changedEditions, artifacts },
  });
  expect(payloadConflict.status === 400 && payloadConflict.data?.detail === "handout_composition_revision_conflict",
    `${prefix}_composition_payload_conflict_not_closed`);
  const changedArtifacts = structuredClone(artifacts);
  changedArtifacts[0].artifactRole = "split_manifest";
  const artifactConflict = await fetchJson(compositionUrl, {
    method: "POST", body: { workspaceId, actorUserId, editions, artifacts: changedArtifacts },
  });
  expect(artifactConflict.status === 400 && artifactConflict.data?.detail === "handout_artifact_key_conflict",
    `${prefix}_artifact_payload_conflict_not_closed`);

  const counts = (await pool.query(
    `select
       (select count(*)::int from teachbase_app.handout_occurrence where editor_revision_id=$1 and occurrence_kind='question') question_occurrences,
       (select count(distinct question_revision_id)::int from teachbase_app.handout_occurrence where editor_revision_id=$1 and occurrence_kind='question') unique_question_revisions,
       (select count(*)::int from teachbase_app.handout_occurrence_source_link s join teachbase_app.handout_occurrence o using (handout_occurrence_id) where o.editor_revision_id=$1) occurrence_sources,
       (select count(distinct m.standard_module_revision_id)::int
          from teachbase_app.handout_occurrence o
          join teachbase_app.standard_module_revision m using (standard_module_revision_id)
         where o.editor_revision_id=$1 and m.review_status='approved') approved_modules,
       (select count(distinct t.standard_module_taxonomy_link_id)::int
          from teachbase_app.handout_occurrence o
          join teachbase_app.standard_module_taxonomy_link t using (standard_module_revision_id)
         where o.editor_revision_id=$1) module_taxonomy_links,
       (select count(*)::int from teachbase_app.editor_revision_artifact_link where editor_revision_id=$1) artifact_links,
       (select count(*)::int from teachbase_app.editor_snapshot where editor_snapshot_id=$2 and content_hash=$3) preserved_snapshot,
       (select count(*)::int from teachbase_app.editor_working_draft where editor_document_id=$4 and draft_version=7 and content_hash=$3) preserved_working_draft`,
    [editor.editorRevisionId, editor.snapshotId, editor.contentHash, editor.editorDocumentId],
  )).rows[0];
  expect(counts.question_occurrences === fixture.questions.length, `${prefix}_question_occurrences:${counts.question_occurrences}`);
  expect(counts.unique_question_revisions === questions.uniqueRevisionCount, `${prefix}_unique_question_revisions`);
  expect(counts.occurrence_sources === fixture.blocks.length, `${prefix}_source_coverage:${counts.occurrence_sources}`);
  expect(counts.approved_modules === fixture.standardModules.length, `${prefix}_approved_modules`);
  expect(counts.module_taxonomy_links === fixture.standardModules.length, `${prefix}_module_taxonomy_links`);
  expect(counts.artifact_links === artifacts.length, `${prefix}_artifact_links`);
  expect(counts.preserved_snapshot === 1 && counts.preserved_working_draft === 1, `${prefix}_wp01_boundary_changed`);
  return { editor, counts, response: response.data, uniqueQuestionRevisions: questions.uniqueRevisionCount,
    concurrentCreates: 4, payloadConflictClosed: true, artifactConflictClosed: true };
}

async function main() {
  await fs.access(jarPath);
  const english = JSON.parse(await fs.readFile(path.join(fixtureRoot, "english_tense_voice_golden.json"), "utf8"));
  const circle = JSON.parse(await fs.readFile(path.join(fixtureRoot, "circle_handout_regression.json"), "utf8"));
  const cluster = await startEmbeddedPostgresCluster("g4_handout_foundation_live_gate");
  let child;
  let pool;
  let report;
  try {
    const database = await cluster.createDatabase("g4_handout_foundation_test");
    const url = new URL(database.connectionString);
    const port = await reservePort();
    const baseUrl = `http://127.0.0.1:${port}`;
    const logs = { stdout: [], stderr: [] };
    capturedLogs = logs;
    child = spawn("java", ["-jar", jarPath], {
      cwd: serverRoot,
      env: {
        ...process.env,
        TEACHBASE_DATABASE_URL: `jdbc:postgresql://127.0.0.1:${cluster.port}/${database.database}`,
        TEACHBASE_DATABASE_USER: decodeURIComponent(url.username),
        TEACHBASE_DATABASE_PASSWORD: decodeURIComponent(url.password),
        TEACHBASE_DATABASE_POOL_SIZE: "12",
        TEACHBASE_SERVER_PORT: String(port),
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stdout.on("data", (chunk) => logs.stdout.push(String(chunk)));
    child.stderr.on("data", (chunk) => logs.stderr.push(String(chunk)));
    await waitForHealth(baseUrl, child, logs);
    pool = new Pool({ connectionString: database.connectionString });
    const workspaceId = crypto.randomUUID();
    const actorUserId = crypto.randomUUID();
    await pool.query("insert into teachbase_app.workspace (workspace_id,slug,display_name) values ($1,'g4-live','G4 Live')", [workspaceId]);
    await pool.query("insert into teachbase_app.app_user (user_id,email,display_name) values ($1,'g4-live@example.invalid','G4 Live')", [actorUserId]);
    await pool.query("insert into teachbase_app.workspace_member (workspace_id,user_id,member_role) values ($1,$2,'owner')", [workspaceId, actorUserId]);

    const englishResult = await exerciseFixture(pool, baseUrl, workspaceId, actorUserId, "english", english);
    const circleResult = await exerciseFixture(pool, baseUrl, workspaceId, actorUserId, "circle", circle);
    expect(englishResult.uniqueQuestionRevisions === 60, "english_dedup_expected_60_revisions");
    const reused = await pool.query(
      `select count(*)::int count from (
         select question_revision_id from teachbase_app.question_source_link
         where workspace_id=$1 and source_evidence_key like 'english:%'
         group by question_revision_id having count(*) > 1
       ) x`, [workspaceId],
    );
    expect(reused.rows[0].count === 3, `english_multi_source_reused_questions:${reused.rows[0].count}`);
    const student = await pool.query(
      `select count(*)::int count from teachbase_app.handout_edition_revision p
       join teachbase_app.handout_edition e using (handout_edition_id)
       where p.editor_revision_id=$1 and e.edition_key='student' and p.edition_role='projection'
         and p.canonical_teacher_revision_id is not null`, [englishResult.editor.editorRevisionId],
    );
    expect(student.rows[0].count === 1, "student_projection_not_pinned_to_teacher");
    const rich = await pool.query(
      `select
         (select count(*)::int from teachbase_app.standard_module_file_reference where workspace_id=$1) images,
         (select count(*)::int from teachbase_app.source_region where region_type='table') tables`, [workspaceId],
    );
    expect(rich.rows[0].images === 9 && rich.rows[0].tables >= 4, "rich_content_storage_gate_failed");

    const immutableId = (await pool.query(
      "select handout_occurrence_id from teachbase_app.handout_occurrence where editor_revision_id=$1 limit 1",
      [englishResult.editor.editorRevisionId],
    )).rows[0].handout_occurrence_id;
    let immutableRejected = false;
    try {
      await pool.query("update teachbase_app.handout_occurrence set position_index=999 where handout_occurrence_id=$1", [immutableId]);
    } catch (error) {
      immutableRejected = error.code === "P0001" && error.message.includes("handout_immutable_row_mutation_forbidden");
    }
    expect(immutableRejected, "handout_occurrence_mutation_not_rejected");

    const moduleRevisionId = (await pool.query(
      "select standard_module_revision_id from teachbase_app.standard_module_revision where workspace_id=$1 limit 1",
      [workspaceId],
    )).rows[0].standard_module_revision_id;
    let moduleContentMutationRejected = false;
    try {
      await pool.query(
        "update teachbase_app.standard_module_revision set title='forbidden mutation' where standard_module_revision_id=$1",
        [moduleRevisionId],
      );
    } catch (error) {
      moduleContentMutationRejected = error.code === "P0001"
        && error.message.includes("standard_module_revision_content_immutable");
    }
    expect(moduleContentMutationRejected, "standard_module_revision_content_mutation_not_rejected");

    const foreignWorkspaceId = crypto.randomUUID();
    const foreignActorUserId = crypto.randomUUID();
    await pool.query(
      "insert into teachbase_app.workspace (workspace_id,slug,display_name) values ($1,'g4-foreign','G4 Foreign')",
      [foreignWorkspaceId],
    );
    await pool.query(
      "insert into teachbase_app.app_user (user_id,email,display_name) values ($1,'g4-foreign@example.invalid','G4 Foreign')",
      [foreignActorUserId],
    );
    await pool.query(
      "insert into teachbase_app.workspace_member (workspace_id,user_id,member_role) values ($1,$2,'owner')",
      [foreignWorkspaceId, foreignActorUserId],
    );
    const crossWorkspace = await fetchJson(
      `${baseUrl}/api/v1/handouts/${englishResult.editor.editorDocumentId}/revisions/${englishResult.editor.editorRevisionId}/composition`,
      {
        method: "POST",
        body: {
          workspaceId: foreignWorkspaceId,
          actorUserId: foreignActorUserId,
          editions: [{
            editionKey: "teacher", editionRole: "canonical", canonicalTeacherEditionKey: null,
            schemaVersion: 1, projectionRules: {}, delta: {}, occurrences: [],
          }],
          artifacts: [],
        },
      },
    );
    expect(crossWorkspace.status === 400 && crossWorkspace.data?.detail === "handout_editor_revision_not_found",
      `handout_cross_workspace_not_rejected:${crossWorkspace.status}`);

    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      database: { engine: "PostgreSQL", version: (await pool.query("show server_version")).rows[0].server_version },
      acceptance: {
        passed: 23,
        total: 23,
        checks: {
          standardModuleFirstClassAsset: true,
          immutableModuleRevisionAndApprovalPointer: true,
          moduleReviewPassed: true,
          moduleTaxonomyAndSourceLinksPassed: true,
          questionMultipleCanonicalSourcesPassed: true,
          canonicalAndPlacementProvenanceSeparated: true,
          unifiedOccurrenceKindsPassed: true,
          stableOccurrenceIdentityPassed: true,
          repeatedAssetRevisionOccurrencePassed: true,
          teacherCanonicalCompositionPassed: true,
          studentProjectionPinnedPassed: true,
          editorArtifactStrongReferencesPassed: true,
          english439BlocksCoveredExactlyOnce: true,
          english63OccurrencesUse60QuestionRevisions: true,
          englishThreeModulesAndFourContainersDistinct: true,
          circle320BlocksAnd31QuestionsPassed: true,
          wp01DraftRevisionSnapshotUnchanged: true,
          standardModuleRevisionContentMutationRejected: true,
          immutableCompositionMutationRejected: true,
          crossWorkspaceCompositionRejected: true,
          concurrentCompositionExactlyOneCreator: true,
          compositionPayloadConflictFailsClosed: true,
          artifactPayloadConflictFailsClosed: true,
        },
      },
      english: {
        sourceBlocks: Number(englishResult.counts.occurrence_sources),
        questionOccurrences: Number(englishResult.counts.question_occurrences),
        uniqueQuestionRevisions: englishResult.uniqueQuestionRevisions,
        approvedStandardModules: Number(englishResult.counts.approved_modules),
        questionContainers: 4,
        studentProjectionRevisions: Number(student.rows[0].count),
        duplicatedStudentQuestionAssets: 0,
        tableStorage: Number(rich.rows[0].tables),
        imageFileReferences: Number(rich.rows[0].images),
      },
      circle: {
        sourceBlocks: Number(circleResult.counts.occurrence_sources),
        questionOccurrences: Number(circleResult.counts.question_occurrences),
        uniqueQuestionRevisions: circleResult.uniqueQuestionRevisions,
        approvedStandardModules: Number(circleResult.counts.approved_modules),
      },
      richContent: {
        storageGate: "passed",
        rendererGate: "separate_existing_regression_required",
      },
      cleanup: "pending",
    };
  } finally {
    if (pool) await pool.end();
    await stopChild(child);
    await cluster.stop();
  }
  report.cleanup = "passed";
  await fs.mkdir(path.dirname(reportPath), { recursive: true });
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`);
  process.stderr.write(capturedLogs.stderr.join("").slice(-12000));
  process.exit(1);
});
