import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

import {
  ensureDir,
  expect,
  readJsonFixture,
  runProcess,
  workspaceRoot,
} from "../helpers/runtime_testkit.mjs";
import {
  mergeSourceRefsJson,
  normalizeQuestionVisualStructure,
} from "../../tools/runtime_visual_split_adapter.mjs";

const TINY_PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9pG5mD0AAAAASUVORK5CYII=";

function cloneJson(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}

function firstDefined(...values) {
  for (const value of values) {
    if (value !== undefined) {
      return value;
    }
  }
  return undefined;
}

export function shortHash(value) {
  return createHash("sha256")
    .update(typeof value === "string" ? value : JSON.stringify(value))
    .digest("hex")
    .slice(0, 12);
}

export async function ensureTinyPng(rootDir, relativePath) {
  const absolutePath = path.join(rootDir, relativePath);
  await ensureDir(path.dirname(absolutePath));
  await fs.writeFile(absolutePath, Buffer.from(TINY_PNG_BASE64, "base64"));
  return absolutePath;
}

export function buildVisualAsset(overrides = {}) {
  const questionUid = String(
    overrides.question_uid ||
      overrides.questionUid ||
      "release_gate_visual_p001_q001"
  ).trim();
  const runtimeRunId = String(
    overrides.runtime_run_id ||
      overrides.runtimeRunId ||
      "run_release_gate_visual_001"
  ).trim();
  const placementScope = String(
    overrides.placement_scope || overrides.placementScope || "option_inline"
  ).trim();
  const optionKey =
    overrides.option_key ??
    overrides.optionKey ??
    (placementScope === "option_inline" ? "A" : "");
  const assetRole =
    overrides.asset_role ||
    overrides.assetRole ||
    (placementScope === "after_analysis"
      ? "analysis"
      : placementScope === "after_stem"
        ? "stem"
        : placementScope === "evidence_only"
          ? "evidence"
          : "option");
  const ordinal = overrides.ordinal || 1;
  const assetId =
    overrides.asset_id ||
    overrides.assetId ||
    `qa_${questionUid}_${assetRole}${optionKey ? `_${optionKey}` : ""}_${String(ordinal).padStart(3, "0")}`;
  const defaultStorageKey =
    placementScope === "option_inline"
      ? `question_assets/${questionUid}/${runtimeRunId}/options/${optionKey || "A"}/${String(ordinal).padStart(3, "0")}.png`
      : `question_assets/${questionUid}/${runtimeRunId}/${assetRole}/${String(ordinal).padStart(3, "0")}.png`;
  return {
    asset_id: assetId,
    asset_role: assetRole,
    option_key: optionKey || null,
    placement_scope: placementScope,
    attach_status:
      firstDefined(overrides.attach_status, overrides.attachStatus) ??
      (placementScope === "evidence_only" ? "not_attached_unassigned" : "attached"),
    file_status:
      firstDefined(overrides.file_status, overrides.fileStatus) ??
      "materialized",
    display_ref:
      firstDefined(overrides.display_ref, overrides.displayRef) ??
      `asset://${assetId}`,
    storage_key:
      firstDefined(overrides.storage_key, overrides.storageKey) ??
      defaultStorageKey,
    bbox_space:
      firstDefined(overrides.bbox_space, overrides.bboxSpace) ??
      "option_crop",
    bbox_json:
      firstDefined(overrides.bbox_json, overrides.bboxJson) ??
      {
        x: 12,
        y: 18,
        w: 160,
        h: 64,
      },
    source_image_asset_id:
      firstDefined(
        overrides.source_image_asset_id,
        overrides.sourceImageAssetId
      ) ??
      `${assetId}_source`,
    source_image_storage_key:
      firstDefined(
        overrides.source_image_storage_key,
        overrides.sourceImageStorageKey
      ) ??
      `source_images/${questionUid}/${runtimeRunId}/${assetId}.png`,
    confidence:
      overrides.confidence === undefined ? 0.95 : overrides.confidence,
    candidate_option_key:
      overrides.candidate_option_key ||
      overrides.candidateOptionKey ||
      optionKey ||
      null,
    runtime_run_id: runtimeRunId,
    review_flags: cloneJson(overrides.review_flags || overrides.reviewFlags || []),
    ...cloneJson(overrides),
  };
}

export function buildQuestionVisualStructure(overrides = {}) {
  const questionUid = String(
    overrides.question_uid ||
      overrides.questionUid ||
      "release_gate_visual_p001_q001"
  ).trim();
  const runtimeRunId = String(
    overrides.runtime_run_id ||
      overrides.runtimeRunId ||
      "run_release_gate_visual_001"
  ).trim();
  const stemText = String(
    overrides.stem_md || overrides.stemMd || "Choose the matching image."
  ).trim();
  const optionAssets = Array.isArray(overrides.visual_assets)
    ? cloneJson(overrides.visual_assets)
    : [buildVisualAsset({ questionUid, runtimeRunId })];
  const optionKey =
    optionAssets.find((asset) => String(asset.placement_scope || "") === "option_inline")
      ?.option_key || "A";
  const defaultOptionAssetIds = optionAssets
    .filter((asset) => String(asset.placement_scope || "") === "option_inline")
    .map((asset) => asset.asset_id);
  const options = Array.isArray(overrides.options)
    ? cloneJson(overrides.options)
    : [
        {
          option_key: optionKey,
          label_md: `${optionKey}.`,
          asset_ids: defaultOptionAssetIds,
          bbox_space: "option_crop",
          bbox_json: { x: 12, y: 18, w: 160, h: 64 },
        },
      ];
  const contentBlocks = Array.isArray(overrides.content_blocks)
    ? cloneJson(overrides.content_blocks)
    : [
        {
          block_id: "blk_stem_001",
          block_order: 1,
          scope: "stem",
          block_type: "markdown",
          text_md: stemText,
        },
        {
          block_id: "blk_option_text_001",
          block_order: 2,
          scope: "option",
          option_key: optionKey,
          block_type: "markdown",
          text_md: `${optionKey}.`,
        },
        ...defaultOptionAssetIds.map((assetId, index) => ({
          block_id: `blk_option_image_${index + 1}`,
          block_order: 3 + index,
          scope: "option",
          option_key: optionKey,
          block_type: "image",
          asset_id: assetId,
          display_ref: `asset://${assetId}`,
        })),
      ];
  const legacyStemMd =
    overrides.legacy_stem_md ||
    overrides.legacyStemMd ||
    [stemText, ...defaultOptionAssetIds.map((assetId) => `![${assetId}](asset://${assetId})`)]
      .filter(Boolean)
      .join("\n\n");
  return normalizeQuestionVisualStructure({
    schema_version: "question_visual_structure.v1.1",
    generated_by: "release_gate_fixture",
    runtime_run_id: runtimeRunId,
    question_uid: questionUid,
    stem_md: stemText,
    answer_md: overrides.answer_md || overrides.answerMd || "A",
    analysis_md:
      overrides.analysis_md || overrides.analysisMd || "Option A matches the prompt.",
    legacy_stem_md: legacyStemMd,
    gating: cloneJson(overrides.gating || { mode: "auto", decision: "choice_detected" }),
    options,
    content_blocks: contentBlocks,
    visual_assets: optionAssets,
    review_flags: cloneJson(overrides.review_flags || overrides.reviewFlags || []),
    ...cloneJson(overrides),
  });
}

export function buildLegacySourceRefs(questionVisualStructure, overrides = {}) {
  const existing = {
    schema_versions: {
      legacy_source_refs: "v0.9",
    },
    legacy_source_refs: {
      document_id: "doc_001",
      page_no: 3,
      crop_artifact_id: "art_crop_old",
    },
    audit: {
      created_by: "old_runtime",
      old_run_id: "run_old",
    },
    manual_note: "人工确认过",
    ...cloneJson(overrides),
  };
  return mergeSourceRefsJson(existing, questionVisualStructure);
}

export function buildVisualManifestImportPayload(tag = "release_gate") {
  const qvs = buildQuestionVisualStructure({
    question_uid: `release_gate_visual_${tag}_q001`,
    runtime_run_id: `run_release_gate_${tag}`,
  });
  return {
    actor: "release_gate_suite",
    bundle_id: `release_gate_visual_bundle_${tag}`,
    lesson_id: `release_gate_visual_lesson_${tag}`,
    title: "Release Gate Visual Lesson",
    track_code: "english_senior",
    subject: "英语",
    stage: "senior",
    grade: "g11",
    season: "autumn",
    source_tree: [
      {
        source_node_local_id: "root",
        node_type: "lesson",
        phase: "reading_main",
        title: "Visual Root",
        checkpoint_codes: ["阅读理解主旨大意"],
      },
    ],
    visualManifest: {
      schema_version: "question_asset_manifest.v0.1",
      generated_at: "2026-07-01T00:00:00.000Z",
      question_count: 1,
      asset_count: qvs.visual_assets.length,
      questions: [
        {
          question_id: `release_gate_visual_question_${tag}`,
          question_uid: qvs.question_uid,
          local_task_id: `RG-${tag.toUpperCase()}`,
          checkpoint: "阅读理解主旨大意",
          component_kind: "single_choice",
          stem_text_md: qvs.legacy_stem_md,
          answer_text_md: qvs.answer_md,
          analysis_text_md: qvs.analysis_md,
          question_visual_structure: qvs,
          merged_source_refs_json: buildLegacySourceRefs(qvs),
        },
      ],
    },
  };
}

export function buildExportPayload({ lessonId, title, stage, grade, season, questions, assetBaseDir }) {
  return {
    lesson: {
      lesson_id: lessonId,
      lesson_title: title || lessonId,
      stage: stage || "senior",
      grade: grade || "g11",
      season: season || "autumn",
      lesson_no: 1,
      source_pdf_name: `${lessonId}.pdf`,
      knowledge_point_count: 1,
      objectives: "Release gate export validation",
    },
    splitLesson: {
      lesson_id: lessonId,
      assetBaseDir,
      question_count: questions.length,
      tree: [
        {
          module: title || lessonId,
          items: ["Release Gate"],
        },
      ],
      auditSummary: {
        reviewedCount: questions.length,
        pendingCount: 0,
      },
      questions,
    },
    reviewQueue: [],
    selectedVersions: ["基础版"],
    selectedAudiences: ["教师版"],
    selectedFormats: ["DOCX"],
    includeCompass: false,
  };
}

export async function importApprovePublish(server, bundleOrPayload, actor = "release_gate_suite") {
  // Visual manifests must stay at the top level so the runtime can invoke the
  // adapter path instead of treating the payload as an empty plain bundle.
  const requestBody =
    bundleOrPayload?.visualManifest && !Array.isArray(bundleOrPayload?.tasks)
      ? {
          actor,
          ...bundleOrPayload,
        }
      : {
          actor,
          bundle: bundleOrPayload,
        };
  const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
    method: "POST",
    body: requestBody,
  });
  expect(imported.ok, `${actor}_import_failed:${JSON.stringify(imported.data)}`);

  const approved = await server.request(
    `/api/runtime/review-tasks/${imported.data.result.reviewTaskId}/approve`,
    {
      method: "POST",
      body: {
        actor: `${actor}_reviewer`,
      },
    }
  );
  expect(approved.ok, `${actor}_approve_failed:${JSON.stringify(approved.data)}`);

  const lessonId = bundleOrPayload.lesson_id;
  const published = await server.request(`/api/runtime/lessons/${lessonId}/publish`, {
    method: "POST",
    body: {
      actor: `${actor}_publisher`,
      lessonRevisionId: imported.data.result.lessonRevisionId,
    },
  });
  expect(published.ok, `${actor}_publish_failed:${JSON.stringify(published.data)}`);

  const detail = await server.request(`/api/runtime/lessons/${lessonId}`);
  expect(detail.ok, `${actor}_detail_failed:${JSON.stringify(detail.data)}`);
  return {
    imported: imported.data.result,
    approved: approved.data.result,
    published: published.data.result,
    detail: detail.data.detail,
  };
}

export async function findCommandOnPath(command) {
  const locator = process.platform === "win32" ? "where" : "which";
  const result = await runProcess(locator, [command]);
  if (result.code !== 0) {
    return null;
  }
  const first = result.stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean);
  return first || null;
}

export async function resolvePgTool(toolName) {
  const directHit = await findCommandOnPath(toolName);
  if (directHit) {
    return directHit;
  }
  const windowsCandidates = [];
  if (process.env.POSTGRES_BIN_DIR) {
    windowsCandidates.push(path.join(process.env.POSTGRES_BIN_DIR, `${toolName}.exe`));
  }
  for (const version of ["18", "17", "16", "15"]) {
    windowsCandidates.push(
      path.join("C:\\", "Program Files", "PostgreSQL", version, "bin", `${toolName}.exe`)
    );
  }
  for (const candidate of windowsCandidates) {
    try {
      await fs.access(candidate);
      return candidate;
    } catch {
      // Keep looking for a local tool before falling back to Docker.
    }
  }
  return null;
}

export function isSafeTestDatabaseUrl(value) {
  const text = String(value || "").trim();
  if (!text) {
    return {
      ok: false,
      reason: "database_url_missing",
    };
  }
  let parsed;
  try {
    parsed = new URL(text);
  } catch {
    return {
      ok: false,
      reason: "database_url_invalid",
    };
  }
  const host = String(parsed.hostname || "").trim().toLowerCase();
  const databaseName = parsed.pathname.replace(/^\//, "");
  if (!["127.0.0.1", "localhost"].includes(host)) {
    return {
      ok: false,
      reason: `database_url_host_not_local:${host}`,
    };
  }
  if (!/(test|ci|integration|tmp|temp)/i.test(databaseName)) {
    return {
      ok: false,
      reason: `database_name_not_test_like:${databaseName}`,
    };
  }
  if (/(prod|production|live|main)/i.test(databaseName)) {
    return {
      ok: false,
      reason: `database_name_looks_production:${databaseName}`,
    };
  }
  return {
    ok: true,
    host,
    databaseName,
  };
}

export async function buildSchemaSnapshot(harness, connectionString) {
  const [tableResult, pkResult, fkResult, columnResult] = await Promise.all([
    harness.queryDatabase(
      connectionString,
      `
        select table_name
        from information_schema.tables
        where table_schema = 'public'
          and table_type = 'BASE TABLE'
        order by table_name
      `
    ),
    harness.queryDatabase(
      connectionString,
      `
        select
          tc.table_name,
          kcu.column_name,
          kcu.ordinal_position
        from information_schema.table_constraints tc
        join information_schema.key_column_usage kcu
          on tc.constraint_name = kcu.constraint_name
         and tc.table_schema = kcu.table_schema
        where tc.table_schema = 'public'
          and tc.constraint_type = 'PRIMARY KEY'
        order by tc.table_name, kcu.ordinal_position
      `
    ),
    harness.queryDatabase(
      connectionString,
      `
        select
          tc.table_name,
          kcu.column_name,
          ccu.table_name as foreign_table_name,
          ccu.column_name as foreign_column_name,
          kcu.ordinal_position
        from information_schema.table_constraints tc
        join information_schema.key_column_usage kcu
          on tc.constraint_name = kcu.constraint_name
         and tc.table_schema = kcu.table_schema
        join information_schema.constraint_column_usage ccu
          on ccu.constraint_name = tc.constraint_name
         and ccu.table_schema = tc.table_schema
        where tc.table_schema = 'public'
          and tc.constraint_type = 'FOREIGN KEY'
        order by tc.table_name, tc.constraint_name, kcu.ordinal_position
      `
    ),
    harness.queryDatabase(
      connectionString,
      `
        select
          table_name,
          column_name,
          data_type,
          udt_name,
          is_nullable,
          column_default,
          ordinal_position
        from information_schema.columns
        where table_schema = 'public'
        order by table_name, ordinal_position
      `
    ),
  ]);

  const pkByTable = new Map();
  for (const row of pkResult.rows) {
    const list = pkByTable.get(row.table_name) || [];
    list.push(row.column_name);
    pkByTable.set(row.table_name, list);
  }

  const fkByTable = new Map();
  for (const row of fkResult.rows) {
    const list = fkByTable.get(row.table_name) || [];
    list.push(`${row.column_name} -> ${row.foreign_table_name}.${row.foreign_column_name}`);
    fkByTable.set(row.table_name, list);
  }

  const columnsByTable = new Map();
  for (const row of columnResult.rows) {
    const list = columnsByTable.get(row.table_name) || [];
    list.push({
      name: row.column_name,
      type: row.data_type === "ARRAY" ? `${row.udt_name}[]` : row.data_type,
      nullable: row.is_nullable === "YES",
      default: row.column_default,
    });
    columnsByTable.set(row.table_name, list);
  }

  const tables = tableResult.rows.map((row) => ({
    table: row.table_name,
    primaryKey: [...(pkByTable.get(row.table_name) || [])].sort(),
    foreignKeys: [...new Set(fkByTable.get(row.table_name) || [])].sort(),
    columns: columnsByTable.get(row.table_name) || [],
  }));

  return {
    tableCount: tables.length,
    tables,
  };
}

export async function buildSeedSummary(harness, connectionString) {
  const result = await harness.queryDatabase(
    connectionString,
    `
      select
        (select count(*)::int from lesson) as lesson_count,
        (select count(*)::int from lesson_revision) as lesson_revision_count,
        (select count(*)::int from task_projection) as task_projection_count,
        (select count(*)::int from question_bank_item_revision) as question_bank_item_revision_count,
        (select count(*)::int from material_item) as material_item_count,
        (select count(*)::int from artifact) as artifact_count,
        (select count(*)::int from artifact_dependency) as artifact_dependency_count,
        (select count(*)::int from publication) as publication_count
    `
  );
  return result.rows[0];
}

export async function readThreeTrackBundles() {
  return {
    math_junior: await readJsonFixture("three_track", "math_junior_bundle.json"),
    math_senior: await readJsonFixture("three_track", "math_senior_bundle.json"),
    english_senior: await readJsonFixture("three_track", "english_senior_bundle.json"),
  };
}
