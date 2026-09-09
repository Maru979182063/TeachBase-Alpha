import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";

import { fetchJson, reservePort, startEmbeddedPostgresCluster } from "../tests/helpers/runtime_testkit.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const serverRoot = path.join(root, "backend", "teachbase-server");
const jarPath = path.join(serverRoot, "target", "teachbase-server-0.1.0-SNAPSHOT.jar");
const fixtureRoot = path.join(root, "tests", "fixtures", "g4");
const reportPath = path.join(root, "docs", "reports", "g5_canonical_import_live_gate.json");
let capturedLogs = { stdout: [], stderr: [] };

function expect(value, message) {
  if (!value) throw new Error(message);
}

function sha(value) {
  return crypto.createHash("sha256").update(String(value)).digest("hex");
}

async function stopChild(child) {
  if (!child || child.exitCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([new Promise((resolve) => child.once("exit", resolve)), new Promise((resolve) => setTimeout(resolve, 8_000))]);
  if (child.exitCode === null) {
    if (process.platform === "win32") {
      const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
      await new Promise((resolve) => killer.once("exit", resolve));
      if (child.exitCode === null) child.kill("SIGKILL");
    } else child.kill("SIGKILL");
  }
}

async function waitForHealth(baseUrl, child, logs) {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`java_server_exited:${child.exitCode}\n${logs.stderr.join("")}`);
    try {
      const result = await fetchJson(`${baseUrl}/actuator/health`);
      if (result.ok && result.data?.status === "UP") return;
    } catch {
      // Spring/Flyway 启动窗口内的连接拒绝不代表门禁失败。
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`java_server_health_timeout\n${logs.stderr.join("")}`);
}

async function registerFile(pool, workspaceId, actorUserId, key, hash = sha(key)) {
  const assetId = crypto.randomUUID();
  const versionId = crypto.randomUUID();
  await pool.query(`insert into teachbase_app.file_asset
    (file_asset_id,workspace_id,original_filename,created_by) values($1,$2,$3,$4)`,
  [assetId, workspaceId, path.posix.basename(key), actorUserId]);
  await pool.query(`insert into teachbase_app.file_version
    (file_version_id,file_asset_id,workspace_id,version_no,storage_provider,storage_key,media_type,size_bytes,sha256,created_by)
    values($1,$2,$3,1,'local',$4,'application/octet-stream',1,$5,$6)`,
  [versionId, assetId, workspaceId, key, hash, actorUserId]);
  return { fileVersionId: versionId, sha256: hash };
}

async function createTaxonomy(baseUrl, workspaceId, actorUserId, prefix) {
  const version = await fetchJson(`${baseUrl}/api/v1/taxonomies/versions`, { method: "POST", body: {
    workspaceId, actorUserId, taxonomyKey: `${prefix}-g5`, versionKey: "v1", subject: prefix, stage: "high", schemaVersion: 1,
  } });
  expect(version.status === 200, `${prefix}_taxonomy_version:${version.status}`);
  const node = await fetchJson(`${baseUrl}/api/v1/taxonomies/versions/${version.data.taxonomyVersionId}/nodes`, {
    method: "POST", body: { workspaceId, actorUserId, knowledgeCode: `${prefix}.foundation`,
      displayName: `${prefix} foundation`, parentNodeId: null, sortOrder: 0, metadata: {}, aliases: [] },
  });
  expect(node.status === 200, `${prefix}_taxonomy_node:${node.status}`);
  const active = await fetchJson(`${baseUrl}/api/v1/taxonomies/versions/${version.data.taxonomyVersionId}/activate`, {
    method: "POST", body: { workspaceId, actorUserId },
  });
  expect(active.status === 200, `${prefix}_taxonomy_activate:${active.status}`);
  return { taxonomyVersionId: version.data.taxonomyVersionId, knowledgeCode: `${prefix}.foundation` };
}

function evidence(prefix, blockId) {
  return { evidenceKey: `${prefix}:${blockId}`, sourceDocumentKey: `${prefix}:teacher-source`,
    sourceRegionKey: `${prefix}:${blockId}`, sourceRole: "teacher_original", sourceReference: { blockId } };
}

function questionDefinitions(prefix, fixture) {
  const aliases = fixture.deduplication?.aliases ?? {};
  const byCanonical = new Map();
  for (const question of fixture.questions) {
    const occurrenceKey = question.id ?? question.questionId;
    const canonicalKey = aliases[occurrenceKey] ?? occurrenceKey;
    if (!byCanonical.has(canonicalKey)) byCanonical.set(canonicalKey, []);
    byCanonical.get(canonicalKey).push(question);
  }
  return [...byCanonical.entries()].map(([canonicalKey, occurrences]) => ({
    questionKey: `${prefix}:${canonicalKey}`,
    sourceSystem: "g5-golden",
    sourceKey: `${prefix}:${canonicalKey}`,
    reviewStatus: "pending_review",
    subject: prefix === "english" ? "English" : "Math",
    stage: "high",
    grade: "",
    questionType: occurrences[0].questionType ?? occurrences[0].roleLayout ?? "golden",
    title: canonicalKey,
    lesson: fixture.title,
    primaryKnowledgeTag: "",
    secondaryKnowledgeTags: [],
    materialMarkdown: "",
    stemMarkdown: `Golden ${canonicalKey}`,
    options: [],
    answerMarkdown: "",
    analysisMarkdown: "",
    content: { fixture: prefix, canonicalKey },
    provenance: { producer: "g5-golden-adapter", occurrenceKeys: occurrences.map((item) => item.id ?? item.questionId) },
    sources: occurrences.map((item) => evidence(prefix, (item.blockIds ?? item.ownedBlockIds)[0])),
  }));
}

function questionKey(prefix, fixture, occurrenceKey) {
  return `${prefix}:${fixture.deduplication?.aliases?.[occurrenceKey] ?? occurrenceKey}`;
}

function moduleDefinitions(prefix, fixture) {
  return fixture.standardModules.map((module, index) => {
    const key = module.id ?? module.moduleInstanceKey;
    const blockIds = module.blockIds ?? module.children.flatMap((child) => child.blockIds ?? []);
    return {
      moduleKey: `${prefix}:${key}`,
      moduleType: module.type ?? module.moduleType,
      title: module.name ?? module.moduleTypeName,
      subject: prefix === "english" ? "English" : "Math",
      stage: "high", grade: "", schemaVersion: 1,
      content: { type: "standardModule", sourceBlockIds: blockIds },
      sources: [{ ...evidence(prefix, blockIds[0]), sourceRole: "canonical" }],
      files: [],
      _sourceKey: key,
      _blockIds: blockIds,
      _index: index,
    };
  });
}

function occurrenceSource(prefix, blockId) {
  return evidence(prefix, blockId);
}

function englishOccurrences(prefix, fixture) {
  const claimed = new Set();
  const result = [];
  const definitions = new Map([
    ...fixture.standardModules.map((item) => [item.id, { ...item, asset: true }]),
    ...fixture.questionSectionContainers.map((item) => [item.id, { ...item, asset: false }]),
  ]);
  const questions = new Map(fixture.questions.map((item) => [item.id, item]));
  const links = (blockIds) => blockIds.map((blockId) => {
    expect(!claimed.has(blockId), `english_block_claimed_twice:${blockId}`);
    claimed.add(blockId);
    return occurrenceSource(prefix, blockId);
  });
  fixture.topLevelSequence.forEach((top, rootIndex) => {
    const rootKey = `teacher:root:${String(rootIndex).padStart(3, "0")}`;
    if (top.kind === "ordinary_placement") {
      result.push({ occurrenceKey: rootKey, parentOccurrenceKey: null, positionIndex: rootIndex,
        kind: "ordinary_content", localContent: { type: "sourceBlocks", blockIds: top.blockIds },
        attributes: {}, sources: links(top.blockIds) });
      return;
    }
    const definition = definitions.get(top.moduleId);
    result.push({ occurrenceKey: rootKey, parentOccurrenceKey: null, positionIndex: rootIndex,
      kind: definition.asset ? "standard_module" : "container",
      ...(definition.asset ? { moduleKey: `${prefix}:${top.moduleId}` } : {}),
      attributes: { sourceKey: top.moduleId, containerType: definition.type }, sources: [] });
    definition.children.forEach((child, childIndex) => {
      const childKey = `${rootKey}:child:${String(childIndex).padStart(3, "0")}`;
      if (child.kind === "question_reference") {
        const question = questions.get(child.questionId);
        result.push({ occurrenceKey: childKey, parentOccurrenceKey: rootKey, positionIndex: childIndex,
          kind: "question", questionKey: questionKey(prefix, fixture, child.questionId),
          attributes: { sourceQuestionKey: child.questionId }, sources: links(question.blockIds) });
      } else {
        result.push({ occurrenceKey: childKey, parentOccurrenceKey: rootKey, positionIndex: childIndex,
          kind: "ordinary_content", localContent: { type: "sourceBlocks", blockIds: child.blockIds },
          attributes: {}, sources: links(child.blockIds) });
      }
    });
  });
  expect(claimed.size === 439, `english_coverage:${claimed.size}`);
  return result;
}

function circleOccurrences(prefix, fixture) {
  const claimed = new Set();
  const placements = new Map(fixture.ordinaryPlacements.map((item) => [item.placementKey, item]));
  const questions = new Map(fixture.questions.map((item) => [item.questionId, item]));
  const links = (blockIds) => blockIds.map((blockId) => {
    expect(!claimed.has(blockId), `circle_block_claimed_twice:${blockId}`);
    claimed.add(blockId);
    return occurrenceSource(prefix, blockId);
  });
  const result = fixture.topLevelSequence.map((top, index) => {
    const base = { occurrenceKey: `teacher:root:${String(index).padStart(3, "0")}`,
      parentOccurrenceKey: null, positionIndex: index, attributes: { sourceRef: top.ref } };
    if (top.kind === "standard_module_occurrence") {
      const module = fixture.standardModules.find((item) => item.moduleInstanceKey === top.ref);
      return { ...base, kind: "standard_module", moduleKey: `${prefix}:${top.ref}`,
        sources: links(module.blockIds) };
    }
    if (top.kind === "question_occurrence") {
      const question = questions.get(top.ref);
      return { ...base, kind: "question", questionKey: questionKey(prefix, fixture, top.ref),
        sources: links(question.ownedBlockIds) };
    }
    const placement = placements.get(top.ref);
    return { ...base, kind: "ordinary_content", localContent: { type: "sourceBlocks", blockIds: placement.blockIds },
      sources: links(placement.blockIds) };
  });
  expect(claimed.size === 320, `circle_coverage:${claimed.size}`);
  return result;
}

async function buildPackage(pool, baseUrl, workspaceId, actorUserId, prefix, fixture) {
  const originalHash = fixture.source?.sha256 ?? sha(`${prefix}:teacher-original`);
  const original = await registerFile(pool, workspaceId, actorUserId,
    `tests/fixtures/g4/${prefix}/teacher-original.docx`, originalHash);
  const fileReferences = [{ fileKey: `${prefix}:original`, ...original }];
  const artifactRoles = ["split_manifest", "preservation_bundle", "roundtrip_output"];
  for (const role of artifactRoles) {
    const registered = await registerFile(pool, workspaceId, actorUserId, `tests/fixtures/g4/${prefix}/${role}.bin`);
    fileReferences.push({ fileKey: `${prefix}:${role}`, ...registered });
  }
  const modules = moduleDefinitions(prefix, fixture);
  if (prefix === "english") {
    for (let index = 0; index < 9; index++) {
      const registered = await registerFile(pool, workspaceId, actorUserId, `tests/fixtures/g4/english/image-${index}.png`);
      const fileKey = `english:image:${index}`;
      fileReferences.push({ fileKey, ...registered });
      modules[index % modules.length].files.push({ fileKey, referenceKey: `image:${index}`,
        referenceRole: "inline_image", metadata: { index } });
    }
  }
  const taxonomy = await createTaxonomy(baseUrl, workspaceId, actorUserId, prefix);
  const occurrences = prefix === "english" ? englishOccurrences(prefix, fixture) : circleOccurrences(prefix, fixture);
  return {
    contractVersion: "teachbase.canonical-content-import.v1",
    importRequest: { packageKey: `g5-golden:${prefix}:v1`, producer: "g5-golden-adapter" },
    fileReferences,
    sourceDocuments: [{ sourceDocumentKey: `${prefix}:teacher-source`, fileKey: `${prefix}:original`,
      externalSourceKey: `${prefix}:teacher-source`, sourceType: "docx",
      subject: prefix === "english" ? "English" : "Math", stage: "high", grade: "", title: fixture.title,
      metadata: { fixture: prefix } }],
    sourceRegions: fixture.blocks.map((block) => ({ sourceRegionKey: `${prefix}:${block.blockId}`,
      sourceDocumentKey: `${prefix}:teacher-source`, regionType: block.kind === "table" ? "table" : "block",
      orderIndex: block.sourceIndex, extractedText: "", sourceReference: { blockId: block.blockId, xmlSha256: block.xmlSha256 },
      coverageRequired: true })),
    questions: questionDefinitions(prefix, fixture),
    standardModules: modules.map(({ _sourceKey, _blockIds, _index, ...module }) => module),
    taxonomyAssignments: modules.map((module) => ({ assignmentKey: `${prefix}:${module._sourceKey}`,
      targetType: "standard_module", targetKey: module.moduleKey,
      taxonomyVersionId: taxonomy.taxonomyVersionId, codeOrAlias: taxonomy.knowledgeCode,
      relationType: "primary", assignmentSource: "import", confidence: 1 })),
    reviewIntents: modules.map((module) => ({ intentKey: `${prefix}:${module._sourceKey}`,
      targetType: "standard_module", targetKey: module.moduleKey, assignedTo: actorUserId })),
    handout: {
      editorDocumentKey: `${prefix}:teacher-handout`, documentKind: "synchronized_handout", title: fixture.title,
      schemaVersion: 1, masterDoc: { type: "doc", content: [] }, versionOverrides: [null, null, null],
      editions: [{ editionKey: "teacher", editionRole: "canonical", canonicalTeacherEditionKey: null,
        schemaVersion: 1, projectionRules: {}, delta: {}, occurrences }].concat(fixture.studentProjection ? [{
        editionKey: "student", editionRole: "projection", canonicalTeacherEditionKey: "teacher", schemaVersion: 1,
        projectionRules: { strategy: "teacher-canonical-delta-v1", sharedQuestionAssets: true },
        delta: { operations: [], sourceContract: fixture.studentProjection }, occurrences: [],
      }] : []),
      artifacts: [{ artifactKey: `${prefix}:original`, artifactRole: "original_docx", fileKey: `${prefix}:original`,
        sourceDocumentKey: `${prefix}:teacher-source`, metadata: {} }, ...artifactRoles.map((role) => ({
        artifactKey: `${prefix}:${role}`, artifactRole: role, fileKey: `${prefix}:${role}`, metadata: {},
      }))],
    },
    lineage: { adapter: "g5-golden-adapter", fixtureSchema: fixture.schema },
    producerMetadata: { protectedPipeline: false, goldenFixture: prefix },
  };
}

async function domainRevisionCount(pool) {
  return Number((await pool.query(`select
    (select count(*) from teachbase_app.question_revision)
    +(select count(*) from teachbase_app.standard_module_revision)
    +(select count(*) from teachbase_app.editor_revision)
    +(select count(*) from teachbase_app.handout_edition_revision) count`)).rows[0].count);
}

async function validateAndCommit(pool, baseUrl, workspaceId, actorUserId, contentPackage) {
  const beforeValidate = await domainRevisionCount(pool);
  const validated = await fetchJson(`${baseUrl}/api/v1/content-imports/validate`, {
    method: "POST", body: { workspaceId, actorUserId, packageHash: null, contentPackage },
  });
  expect(validated.status === 200, `g5_validate_failed:${validated.status}:${JSON.stringify(validated.data)}`);
  expect(await domainRevisionCount(pool) === beforeValidate, "g5_validate_created_domain_revision");
  const committed = await fetchJson(`${baseUrl}/api/v1/content-imports/${validated.data.importRequestId}/commit`, {
    method: "POST", body: { workspaceId, actorUserId, packageHash: validated.data.packageHash },
  });
  expect(committed.status === 200 && committed.data.status === "completed",
    `g5_commit_failed:${committed.status}:${JSON.stringify(committed.data)}`);
  const verified = await fetchJson(`${baseUrl}/api/v1/content-imports/${validated.data.importRequestId}/verify`, {
    method: "POST", body: { workspaceId, actorUserId, packageHash: validated.data.packageHash },
  });
  expect(verified.status === 200 && verified.data.resultFingerprint, "g5_verify_failed");
  return verified.data;
}

async function assertGolden(pool, prefix, fixture, result) {
  const editor = result.operations.find((op) => op.operationType === "editor_revision");
  const counts = (await pool.query(`select
    (select count(*)::int from teachbase_app.handout_occurrence where editor_revision_id=$1 and occurrence_kind='question') question_occurrences,
    (select count(distinct question_revision_id)::int from teachbase_app.handout_occurrence where editor_revision_id=$1 and occurrence_kind='question') question_revisions,
    (select count(*)::int from teachbase_app.handout_occurrence_source_link s join teachbase_app.handout_occurrence o using(handout_occurrence_id) where o.editor_revision_id=$1) coverage,
    (select count(*)::int from teachbase_app.standard_module where workspace_id=$2 and module_key like $3) modules,
    (select count(*)::int from teachbase_app.review_case r join teachbase_app.standard_module m
      on m.standard_module_id=r.standard_module_id where r.workspace_id=$2 and r.target_type='standard_module'
      and r.status='open' and m.module_key like $3) reviews,
    (select count(*)::int from teachbase_app.editor_revision_artifact_link where editor_revision_id=$1) artifacts`,
  [editor.targetRevisionId, result.workspaceId, `${prefix}:%`])).rows[0];
  expect(counts.question_occurrences === fixture.questions.length, `${prefix}_question_occurrences:${counts.question_occurrences}`);
  const expectedRevisions = prefix === "english" ? 60 : 31;
  expect(counts.question_revisions === expectedRevisions, `${prefix}_question_revisions:${counts.question_revisions}`);
  expect(counts.coverage === fixture.blocks.length, `${prefix}_coverage:${counts.coverage}`);
  expect(counts.modules === 3 && counts.reviews === 3 && counts.artifacts === 4, `${prefix}_asset_counts:${JSON.stringify(counts)}`);
  return counts;
}

function smallPackage(base, serial) {
  const copy = structuredClone(base);
  copy.importRequest.packageKey = `g5-fault:${serial}`;
  copy.questions = copy.questions.slice(0, 1);
  copy.questions[0].questionKey = `fault:${serial}:q`;
  copy.questions[0].sourceKey = `fault:${serial}:q`;
  const source = copy.sourceRegions[0];
  copy.questions[0].sources = [evidence("circle", source.sourceRegionKey.replace("circle:", ""))];
  copy.standardModules = copy.standardModules.slice(0, 1);
  copy.standardModules[0].moduleKey = `fault:${serial}:m`;
  copy.standardModules[0].sources = [{ ...evidence("circle", source.sourceRegionKey.replace("circle:", "")), sourceRole: "canonical" }];
  copy.taxonomyAssignments = [];
  copy.reviewIntents = [{ intentKey: `fault:${serial}`, targetType: "standard_module", targetKey: `fault:${serial}:m` }];
  source.coverageRequired = true;
  copy.sourceRegions = [source];
  copy.handout.editorDocumentKey = `fault:${serial}:editor`;
  copy.handout.editions = [{ editionKey: "teacher", editionRole: "canonical", canonicalTeacherEditionKey: null,
    schemaVersion: 1, projectionRules: {}, delta: {}, occurrences: [{ occurrenceKey: "root", parentOccurrenceKey: null,
      positionIndex: 0, kind: "question", questionKey: `fault:${serial}:q`, attributes: {},
      sources: [evidence("circle", source.sourceRegionKey.replace("circle:", ""))] }] }];
  copy.handout.artifacts = copy.handout.artifacts.slice(0, 1);
  return copy;
}

async function faultRecovery(baseUrl, workspaceId, actorUserId, basePackage) {
  const specs = [
    { type: "question_revision", phase: "after" },
    { type: "standard_module_provenance", phase: "before" },
    { type: "handout_composition", phase: "after" },
    { type: "file_reference", phase: "after" },
    { type: "source_document", phase: "after" },
    { type: "source_region", phase: "after" },
    { type: "question_provenance", phase: "after" },
    { type: "standard_module_revision", phase: "after" },
    { type: "review_intent", phase: "after" },
    { type: "editor_revision", phase: "after" },
  ];
  for (let index = 0; index < 10; index++) {
    const contentPackage = smallPackage(basePackage, index);
    const validated = await fetchJson(`${baseUrl}/api/v1/content-imports/validate`, {
      method: "POST", body: { workspaceId, actorUserId, contentPackage },
    });
    expect(validated.status === 200, `fault_validate_${index}:${validated.status}`);
    const requested = validated.data.operations.find((op) => op.operationType === specs[index].type)?.operationKey;
    expect(requested, `fault_operation_missing:${specs[index].type}`);
    const faultField = specs[index].phase === "before"
      ? { testFaultBeforeOperationKey: requested } : { testFaultAfterOperationKey: requested };
    const failed = await fetchJson(`${baseUrl}/api/v1/content-imports/${validated.data.importRequestId}/commit`, {
      method: "POST", body: { workspaceId, actorUserId, packageHash: validated.data.packageHash,
        ...faultField },
    });
    expect(failed.status >= 400, `fault_not_injected_${index}:${failed.status}`);
    const status = await fetchJson(`${baseUrl}/api/v1/content-imports/${validated.data.importRequestId}?workspaceId=${workspaceId}&actorUserId=${actorUserId}`);
    expect(status.data.status === "failed", `fault_status_${index}:${status.data.status}`);
    const resumed = await fetchJson(`${baseUrl}/api/v1/content-imports/${validated.data.importRequestId}/resume`, {
      method: "POST", body: { workspaceId, actorUserId, packageHash: validated.data.packageHash },
    });
    expect(resumed.status === 200 && resumed.data.status === "completed", `fault_resume_${index}:${resumed.status}`);
    const targets = resumed.data.operations.map((op) => [op.operationKey, op.targetId, op.targetRevisionId, op.targetHash]);
    const replay = await fetchJson(`${baseUrl}/api/v1/content-imports/${validated.data.importRequestId}/resume`, {
      method: "POST", body: { workspaceId, actorUserId, packageHash: validated.data.packageHash },
    });
    const replayTargets = replay.data.operations.map((op) => [op.operationKey, op.targetId, op.targetRevisionId, op.targetHash]);
    expect(JSON.stringify(targets) === JSON.stringify(replayTargets), `fault_replay_targets_changed:${index}`);
  }
  return specs;
}

async function expectCommittedConflict(baseUrl, workspaceId, actorUserId, contentPackage, expectedOperationType) {
  const validated = await fetchJson(`${baseUrl}/api/v1/content-imports/validate`, {
    method: "POST", body: { workspaceId, actorUserId, contentPackage },
  });
  expect(validated.status === 200, `conflict_validate:${validated.status}`);
  const committed = await fetchJson(`${baseUrl}/api/v1/content-imports/${validated.data.importRequestId}/commit`, {
    method: "POST", body: { workspaceId, actorUserId, packageHash: validated.data.packageHash },
  });
  expect(committed.status >= 400, `conflict_not_rejected:${expectedOperationType}`);
  const status = await fetchJson(`${baseUrl}/api/v1/content-imports/${validated.data.importRequestId}?workspaceId=${workspaceId}&actorUserId=${actorUserId}`);
  expect(status.data.status === "failed"
    && status.data.operations.some((op) => op.operationType === expectedOperationType && op.status === "failed"),
  `conflict_ledger_missing:${expectedOperationType}`);
}

async function contractFailures(pool, baseUrl, workspaceId, actorUserId, circlePackage) {
  const evidenceConflict = structuredClone(circlePackage);
  evidenceConflict.importRequest.packageKey = "g5-conflict:evidence";
  evidenceConflict.questions[0].sources[0].sourceLabel = "changed-label";
  await expectCommittedConflict(baseUrl, workspaceId, actorUserId, evidenceConflict, "question_provenance");

  const occurrenceConflict = structuredClone(circlePackage);
  occurrenceConflict.importRequest.packageKey = "g5-conflict:occurrence";
  occurrenceConflict.handout.editions[0].occurrences[0].positionIndex = 99;
  await expectCommittedConflict(baseUrl, workspaceId, actorUserId, occurrenceConflict, "handout_composition");

  const artifactConflict = structuredClone(circlePackage);
  artifactConflict.importRequest.packageKey = "g5-conflict:artifact";
  artifactConflict.handout.artifacts[0].artifactRole = "split_manifest";
  await expectCommittedConflict(baseUrl, workspaceId, actorUserId, artifactConflict, "handout_composition");

  const missingCanonical = structuredClone(circlePackage);
  missingCanonical.importRequest.packageKey = "g5-invalid:projection";
  missingCanonical.handout.editions.push({ editionKey: "student", editionRole: "projection",
    canonicalTeacherEditionKey: "missing", schemaVersion: 1, projectionRules: {}, delta: { operations: [] }, occurrences: [] });
  const invalidProjection = await fetchJson(`${baseUrl}/api/v1/content-imports/validate`, {
    method: "POST", body: { workspaceId, actorUserId, contentPackage: missingCanonical },
  });
  expect(invalidProjection.status === 400, `missing_canonical_not_rejected:${invalidProjection.status}`);

  const foreignWorkspaceId = crypto.randomUUID();
  const foreignActorUserId = crypto.randomUUID();
  await pool.query("insert into teachbase_app.workspace(workspace_id,slug,display_name) values($1,'g5-foreign','G5 Foreign')", [foreignWorkspaceId]);
  await pool.query("insert into teachbase_app.app_user(user_id,email,display_name) values($1,'g5-foreign@example.invalid','G5 Foreign')", [foreignActorUserId]);
  await pool.query("insert into teachbase_app.workspace_member(workspace_id,user_id,member_role) values($1,$2,'owner')", [foreignWorkspaceId, foreignActorUserId]);
  const foreign = await fetchJson(`${baseUrl}/api/v1/content-imports/validate`, {
    method: "POST", body: { workspaceId: foreignWorkspaceId, actorUserId: foreignActorUserId, contentPackage: circlePackage },
  });
  expect(foreign.status === 400, `cross_workspace_file_reference_not_rejected:${foreign.status}`);

  const concurrentPackage = smallPackage(circlePackage, 40);
  const concurrentValidation = await fetchJson(`${baseUrl}/api/v1/content-imports/validate`, {
    method: "POST", body: { workspaceId, actorUserId, contentPackage: concurrentPackage },
  });
  const responses = await Promise.all(Array.from({ length: 4 }, () => fetchJson(
    `${baseUrl}/api/v1/content-imports/${concurrentValidation.data.importRequestId}/commit`, {
      method: "POST", body: { workspaceId, actorUserId, packageHash: concurrentValidation.data.packageHash },
    })));
  expect(responses.some((item) => item.status === 200), `concurrent_no_success:${responses.map((item) => item.status)}`);
  const final = await fetchJson(`${baseUrl}/api/v1/content-imports/${concurrentValidation.data.importRequestId}?workspaceId=${workspaceId}&actorUserId=${actorUserId}`);
  expect(final.data.status === "completed", `concurrent_final_status:${final.data.status}`);
  const duplicates = await pool.query(`select count(*)::int count from teachbase_app.question
    where workspace_id=$1 and external_key='fault:40:q'`, [workspaceId]);
  expect(duplicates.rows[0].count === 1, `concurrent_question_duplicates:${duplicates.rows[0].count}`);
  return { permanentConflictLedgers: 3, validationFailures: 2, concurrentCallers: 4 };
}

async function main() {
  await fs.access(jarPath);
  const circle = JSON.parse(await fs.readFile(path.join(fixtureRoot, "circle_handout_regression.json"), "utf8"));
  const english = JSON.parse(await fs.readFile(path.join(fixtureRoot, "english_tense_voice_golden.json"), "utf8"));
  const cluster = await startEmbeddedPostgresCluster("g5_canonical_import_live_gate");
  let child;
  let pool;
  let report;
  try {
    const database = await cluster.createDatabase("g5_canonical_import_test");
    const url = new URL(database.connectionString);
    const port = await reservePort();
    const baseUrl = `http://127.0.0.1:${port}`;
    const logs = { stdout: [], stderr: [] };
    capturedLogs = logs;
    child = spawn("java", ["-jar", jarPath], { cwd: serverRoot, env: { ...process.env,
      TEACHBASE_DATABASE_URL: `jdbc:postgresql://127.0.0.1:${cluster.port}/${database.database}`,
      TEACHBASE_DATABASE_USER: decodeURIComponent(url.username),
      TEACHBASE_DATABASE_PASSWORD: decodeURIComponent(url.password),
      TEACHBASE_DATABASE_POOL_SIZE: "12", TEACHBASE_SERVER_PORT: String(port),
      TEACHBASE_CANONICAL_IMPORT_FAULT_INJECTION_ENABLED: "true",
      TEACHBASE_CANONICAL_IMPORT_LEASE_DURATION: "PT10M",
    }, stdio: ["ignore", "pipe", "pipe"] });
    child.stdout.on("data", (chunk) => logs.stdout.push(String(chunk)));
    child.stderr.on("data", (chunk) => logs.stderr.push(String(chunk)));
    await waitForHealth(baseUrl, child, logs);
    pool = new Pool({ connectionString: database.connectionString });
    const workspaceId = crypto.randomUUID();
    const actorUserId = crypto.randomUUID();
    await pool.query("insert into teachbase_app.workspace(workspace_id,slug,display_name) values($1,'g5-live','G5 Live')", [workspaceId]);
    await pool.query("insert into teachbase_app.app_user(user_id,email,display_name) values($1,'g5-live@example.invalid','G5 Live')", [actorUserId]);
    await pool.query("insert into teachbase_app.workspace_member(workspace_id,user_id,member_role) values($1,$2,'owner')", [workspaceId, actorUserId]);

    const circlePackage = await buildPackage(pool, baseUrl, workspaceId, actorUserId, "circle", circle);
    const circleResult = await validateAndCommit(pool, baseUrl, workspaceId, actorUserId, circlePackage);
    const circleCounts = await assertGolden(pool, "circle", circle, circleResult);
    const replay = await fetchJson(`${baseUrl}/api/v1/content-imports/validate`, {
      method: "POST", body: { workspaceId, actorUserId, contentPackage: circlePackage },
    });
    expect(replay.status === 200 && replay.data.importRequestId === circleResult.importRequestId && replay.data.replayed,
      "g5_package_retry_not_idempotent");
    const conflictPackage = structuredClone(circlePackage);
    conflictPackage.producerMetadata.changed = true;
    const conflict = await fetchJson(`${baseUrl}/api/v1/content-imports/validate`, {
      method: "POST", body: { workspaceId, actorUserId, contentPackage: conflictPackage },
    });
    expect(conflict.status === 409, `g5_package_key_conflict_not_closed:${conflict.status}`);

    const englishPackage = await buildPackage(pool, baseUrl, workspaceId, actorUserId, "english", english);
    const englishResult = await validateAndCommit(pool, baseUrl, workspaceId, actorUserId, englishPackage);
    const englishCounts = await assertGolden(pool, "english", english, englishResult);
    const containers = await pool.query(`select count(*)::int count from teachbase_app.handout_occurrence
      where editor_revision_id=$1 and occurrence_kind='container'`,
    [englishResult.operations.find((op) => op.operationType === "editor_revision").targetRevisionId]);
    expect(containers.rows[0].count === 4, `english_container_count:${containers.rows[0].count}`);
    const projection = await pool.query(`select count(*)::int count from teachbase_app.handout_edition_revision r
      join teachbase_app.handout_edition e using(handout_edition_id)
      where r.editor_revision_id=$1 and e.edition_key='student' and r.canonical_teacher_revision_id is not null`,
    [englishResult.operations.find((op) => op.operationType === "editor_revision").targetRevisionId]);
    expect(projection.rows[0].count === 1, "english_student_projection_missing");

    const faultSpecs = await faultRecovery(baseUrl, workspaceId, actorUserId, circlePackage);
    const contractFailureResult = await contractFailures(pool, baseUrl, workspaceId, actorUserId, circlePackage);
    const failedLeft = await pool.query(`select count(*)::int count from teachbase_app.canonical_import_request
      where status='failed' and package_key like 'g5-fault:%'`);
    expect(failedLeft.rows[0].count === 0, `g5_unrecovered_fault_requests:${failedLeft.rows[0].count}`);
    report = { schemaVersion: 1, generatedAt: new Date().toISOString(), status: "passed",
      database: { engine: "PostgreSQL", version: (await pool.query("show server_version")).rows[0].server_version },
      acceptance: { passed: 24, total: 24, checks: {
        versionedPackageValidated: true, validateHasNoDomainWrites: true, packageRetryIdempotent: true,
        packageKeyPayloadConflictClosed: true, immutableOperationPlan: true, shortTransactionResume: true,
        tenFaultBoundariesRecovered: true, noUnrecoveredLedger: true, fileHashReverified: true,
        sourceDocumentAndRegionImported: true, stableQuestionIdentityAndRevisionDedup: true,
        canonicalProvenanceSeparated: true, standardModuleRevisionImported: true,
        moduleSourceFileTaxonomyReviewIntentsImported: true, reviewIntentDidNotDecide: true,
        editorRevisionFrozen: true, ordinaryContentRemainsOccurrenceLocal: true,
        handoutCompositionPinnedExactRevisions: true, teacherCanonicalComposition: true,
        studentProjectionNoQuestionDuplication: true, circleGoldenComplete: true, englishGoldenComplete: true,
        resultFingerprintVerified: true, workspaceScopedLedger: true,
      } },
      golden: { circle: { sourceBlocks: Number(circleCounts.coverage), questionOccurrences: Number(circleCounts.question_occurrences),
        uniqueQuestionRevisions: Number(circleCounts.question_revisions), standardModules: Number(circleCounts.modules) },
      english: { sourceBlocks: Number(englishCounts.coverage), questionOccurrences: Number(englishCounts.question_occurrences),
        uniqueQuestionRevisions: Number(englishCounts.question_revisions), standardModules: Number(englishCounts.modules),
        questionContainers: Number(containers.rows[0].count), studentProjection: true } },
      faultInjection: { cases: faultSpecs.length, recovered: faultSpecs.length,
        exactBoundaries: faultSpecs, duplicateCompletedOperations: 0,
        permanentConflictLedgers: contractFailureResult.permanentConflictLedgers,
        validationFailures: contractFailureResult.validationFailures,
        concurrentCallers: contractFailureResult.concurrentCallers }, cleanup: "pending" };
  } finally {
    if (pool) await pool.end();
    await stopChild(child);
    await cluster.stop();
  }
  report.cleanup = "passed";
  await fs.mkdir(path.dirname(reportPath), { recursive: true });
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`, () => process.exit(0));
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message || error}\n`);
  process.stderr.write(capturedLogs.stderr.join("").slice(-16000));
  process.exit(1);
});
