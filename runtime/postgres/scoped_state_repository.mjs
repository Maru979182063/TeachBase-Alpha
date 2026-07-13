/**
 * Purpose:
 * - hydrate only the rows a write operation actually needs instead of replaying
 *   the entire runtime state on every Postgres mutation.
 * - keep validation-stage domain mutators reusable while shrinking the write
 *   scope to the concrete lesson/build/projection facts involved in the action.
 */

import { normalizeState } from "../../tools/runtime_backbone_store.mjs";
import {
  runtimeMetadataConfig,
  stateTableConfigMap,
} from "./state_table_configs.mjs";

function quoteIdent(identifier) {
  return `"${String(identifier).replace(/"/g, "\"\"")}"`;
}

function buildSelectExpression(column) {
  const quotedColumn = quoteIdent(column);
  if (column.endsWith("_at")) {
    return `case when ${quotedColumn} is null then null else to_char(${quotedColumn} at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as ${quotedColumn}`;
  }
  return quotedColumn;
}

function uniqueStrings(values = []) {
  return [...new Set((values || []).map((value) => String(value || "").trim()).filter(Boolean))];
}

async function selectConfiguredRows(client, config, whereSql = "", params = []) {
  const result = await client.query(
    `
      select to_jsonb(source_row) as row_json
      from (
        select ${config.readColumns.map(buildSelectExpression).join(", ")}
        from ${quoteIdent(config.table)}
        ${whereSql}
      ) as source_row
    `,
    params
  );
  return result.rows.map((row) => row.row_json);
}

async function selectStateRows(client, stateKey, whereSql = "", params = []) {
  const config = stateTableConfigMap.get(stateKey);
  if (!config) {
    throw new Error(`unknown_state_table_config:${stateKey}`);
  }
  return selectConfiguredRows(client, config, whereSql, params);
}

async function loadRuntimeMetadata(client, snapshotKey = "default") {
  const result = await client.query(
    `
      select to_jsonb(source_row) as row_json
      from (
        select ${runtimeMetadataConfig.writeColumns.map(buildSelectExpression).join(", ")}
        from ${quoteIdent(runtimeMetadataConfig.table)}
        where ${quoteIdent(runtimeMetadataConfig.primaryKey)} = $1
      ) as source_row
    `,
    [snapshotKey]
  );
  const row = result.rows[0]?.row_json || {};
  const now = new Date().toISOString();
  return {
    generatedAt: row.generated_at || now,
    updatedAt: row.updated_at || row.generated_at || now,
    source: row.source || "postgres_normalized_tables",
  };
}

async function buildScopedStateShell(client, snapshotKey = "default") {
  return normalizeState({
    meta: await loadRuntimeMetadata(client, snapshotKey),
  });
}

async function loadCheckpointCatalogScope(client, state, catalogScope = null) {
  const key = catalogScope
    ? `${catalogScope.subject}|${catalogScope.stage}|${catalogScope.grade}`
    : "";
  if (!key) {
    return;
  }
  state.checkpointCatalogs = await selectStateRows(
    client,
    "checkpointCatalogs",
    `where key = $1 order by created_at asc`,
    [key]
  );
  const catalogIds = uniqueStrings(
    state.checkpointCatalogs.map((item) => item.catalog_id)
  );
  if (!catalogIds.length) {
    return;
  }
  state.checkpointCatalogVersions = await selectStateRows(
    client,
    "checkpointCatalogVersions",
    `where catalog_id = any($1::text[]) order by created_at asc`,
    [catalogIds]
  );
  const catalogVersionIds = uniqueStrings(
    state.checkpointCatalogVersions.map((item) => item.catalog_version_id)
  );
  if (!catalogVersionIds.length) {
    return;
  }
  state.checkpointNodes = await selectStateRows(
    client,
    "checkpointNodes",
    `where catalog_version_id = any($1::text[]) order by order_index asc, created_at asc`,
    [catalogVersionIds]
  );
}

export async function loadLessonScopedRuntimeState(
  client,
  {
    lessonId,
    bundleId = null,
    catalogScope = null,
    includeArtifacts = true,
    includeImports = true,
    includeTaskProjections = true,
    includePublications = true,
    includeReviewTasks = true,
    includeQualityEvaluations = true,
  } = {},
  snapshotKey = "default"
) {
  const state = await buildScopedStateShell(client, snapshotKey);
  const targetLessonId = String(lessonId || "").trim();
  if (!targetLessonId) {
    if (bundleId) {
      state.imports = await selectStateRows(
        client,
        "imports",
        `where bundle_id = $1 order by created_at asc`,
        [bundleId]
      );
    }
    await loadCheckpointCatalogScope(client, state, catalogScope);
    return state;
  }

  state.lessons = await selectStateRows(
    client,
    "lessons",
    `where lesson_id = $1 order by created_at asc`,
    [targetLessonId]
  );
  const lesson = state.lessons[0] || null;
  const effectiveCatalogScope = catalogScope || (lesson
    ? {
        subject: lesson.subject,
        stage: lesson.stage,
        grade: lesson.grade,
      }
    : null);

  state.lessonRevisions = await selectStateRows(
    client,
    "lessonRevisions",
    `where lesson_id = $1 order by revision_no asc, created_at asc`,
    [targetLessonId]
  );
  const lessonRevisionIds = uniqueStrings(
    state.lessonRevisions.map((item) => item.lesson_revision_id)
  );

  if (lesson?.document_group_id) {
    state.documentGroups = await selectStateRows(
      client,
      "documentGroups",
      `where document_group_id = $1 order by created_at asc`,
      [lesson.document_group_id]
    );
    state.documentGroupMembers = await selectStateRows(
      client,
      "documentGroupMembers",
      `where document_group_id = $1 order by sort_index asc, created_at asc`,
      [lesson.document_group_id]
    );
    const documentIds = uniqueStrings(
      state.documentGroupMembers.map((item) => item.document_id)
    );
    if (documentIds.length) {
      state.documents = await selectStateRows(
        client,
        "documents",
        `where document_id = any($1::text[]) order by created_at asc`,
        [documentIds]
      );
      const sourceIds = uniqueStrings(
        state.documents.map((item) => item.source_id)
      );
      if (sourceIds.length) {
        state.documentSources = await selectStateRows(
          client,
          "documentSources",
          `where source_id = any($1::text[]) order by created_at asc`,
          [sourceIds]
        );
      }
      state.documentRelations = await selectStateRows(
        client,
        "documentRelations",
        `where from_document_id = any($1::text[]) or to_document_id = any($1::text[]) order by created_at asc`,
        [documentIds]
      );
      state.pageAssets = await selectStateRows(
        client,
        "pageAssets",
        `where document_id = any($1::text[]) order by page_no asc, created_at asc`,
        [documentIds]
      );
    }
  }

  state.sourceNodes = await selectStateRows(
    client,
    "sourceNodes",
    `where lesson_id = $1 order by created_at asc`,
    [targetLessonId]
  );
  if (lessonRevisionIds.length) {
    state.sourceNodeRevisions = await selectStateRows(
      client,
      "sourceNodeRevisions",
      `where lesson_revision_id = any($1::text[]) order by created_at asc`,
      [lessonRevisionIds]
    );
  }
  const sourceNodeRevisionIds = uniqueStrings(
    state.sourceNodeRevisions.map((item) => item.source_node_revision_id)
  );
  if (sourceNodeRevisionIds.length) {
    state.sourceNodeCheckpointLinks = await selectStateRows(
      client,
      "sourceNodeCheckpointLinks",
      `where source_node_revision_id = any($1::text[]) order by created_at asc`,
      [sourceNodeRevisionIds]
    );
  }

  state.tasks = await selectStateRows(
    client,
    "tasks",
    `where lesson_id = $1 order by created_at asc`,
    [targetLessonId]
  );
  const taskIds = uniqueStrings(state.tasks.map((item) => item.task_id));
  if (lessonRevisionIds.length || taskIds.length) {
    const taskRevisionParams = [];
    const taskRevisionWhere = [];
    if (lessonRevisionIds.length) {
      taskRevisionParams.push(lessonRevisionIds);
      taskRevisionWhere.push(
        `lesson_revision_id = any($${taskRevisionParams.length}::text[])`
      );
    }
    if (taskIds.length) {
      taskRevisionParams.push(taskIds);
      taskRevisionWhere.push(`task_id = any($${taskRevisionParams.length}::text[])`);
    }
    state.taskRevisions = await selectStateRows(
      client,
      "taskRevisions",
      `where ${taskRevisionWhere.join(" or ")} order by created_at asc`,
      taskRevisionParams
    );
  }
  const taskRevisionIds = uniqueStrings(
    state.taskRevisions.map((item) => item.task_revision_id)
  );
  if (taskRevisionIds.length) {
    state.taskSubjectExt = await selectStateRows(
      client,
      "taskSubjectExt",
      `where task_revision_id = any($1::text[]) order by created_at asc`,
      [taskRevisionIds]
    );
    state.taskCheckpointOverrides = await selectStateRows(
      client,
      "taskCheckpointOverrides",
      `where task_revision_id = any($1::text[]) order by created_at asc`,
      [taskRevisionIds]
    );
  }

  const pageAssetIds = uniqueStrings(
    state.pageAssets.map((item) => item.page_asset_id)
  );
  if (pageAssetIds.length) {
    state.components = await selectStateRows(
      client,
      "components",
      `where page_asset_id = any($1::text[]) order by created_at asc`,
      [pageAssetIds]
    );
  }
  const componentIds = uniqueStrings(
    state.components.map((item) => item.component_id)
  );
  if (componentIds.length || taskRevisionIds.length) {
    const componentRevisionParams = [];
    const componentRevisionWhere = [];
    if (componentIds.length) {
      componentRevisionParams.push(componentIds);
      componentRevisionWhere.push(
        `component_id = any($${componentRevisionParams.length}::text[])`
      );
    }
    if (taskRevisionIds.length) {
      componentRevisionParams.push(taskRevisionIds);
      componentRevisionWhere.push(
        `source_task_revision_id = any($${componentRevisionParams.length}::text[])`
      );
    }
    state.componentRevisions = await selectStateRows(
      client,
      "componentRevisions",
      `where ${componentRevisionWhere.join(" or ")} order by created_at asc`,
      componentRevisionParams
    );
    state.componentLinks = await selectStateRows(
      client,
      "componentLinks",
      `where component_id = any($1::text[]) or target_revision_id = any($2::text[]) order by created_at asc`,
      [componentIds, taskRevisionIds]
    );
  }

  if (includeTaskProjections) {
    state.taskProjections = await selectStateRows(
      client,
      "taskProjections",
      `where lesson_id = $1 order by created_at asc`,
      [targetLessonId]
    );
  }
  if (includeImports) {
    if (bundleId) {
      state.imports = await selectStateRows(
        client,
        "imports",
        `where lesson_id = $1 or bundle_id = $2 order by created_at asc`,
        [targetLessonId, bundleId]
      );
    } else {
      state.imports = await selectStateRows(
        client,
        "imports",
        `where lesson_id = $1 order by created_at asc`,
        [targetLessonId]
      );
    }
  }
  if (includePublications) {
    state.publications = await selectStateRows(
      client,
      "publications",
      `where lesson_id = $1 order by created_at asc`,
      [targetLessonId]
    );
  }
  if (includeReviewTasks && (lessonRevisionIds.length || taskRevisionIds.length)) {
    state.reviewTasks = await selectStateRows(
      client,
      "reviewTasks",
      `where target_revision_id = any($1::text[]) or target_revision_id = any($2::text[]) order by created_at asc`,
      [lessonRevisionIds, taskRevisionIds]
    );
  }
  if (includeQualityEvaluations && lessonRevisionIds.length) {
    state.qualityEvaluations = await selectStateRows(
      client,
      "qualityEvaluations",
      `where target_revision_id = any($1::text[]) order by evaluated_at asc`,
      [lessonRevisionIds]
    );
  }
  if (includeArtifacts) {
    state.artifacts = await selectStateRows(
      client,
      "artifacts",
      `where coalesce(summary_json->>'lesson_id', '') = $1 order by created_at asc`,
      [targetLessonId]
    );
  }

  await loadCheckpointCatalogScope(client, state, effectiveCatalogScope);
  return state;
}

function extractImportScope(payload = {}) {
  const bundle = payload.bundle && typeof payload.bundle === "object" ? payload.bundle : {};
  return {
    lessonId:
      payload.lesson_id ||
      payload.lessonId ||
      bundle.lesson_id ||
      payload.lesson?.lesson_id ||
      "",
    bundleId:
      payload.bundle_id ||
      payload.bundleId ||
      bundle.bundle_id ||
      "",
    catalogScope: {
      subject:
        payload.subject ||
        bundle.subject ||
        payload.lesson?.subject ||
        "",
      stage:
        payload.stage ||
        bundle.stage ||
        payload.lesson?.stage ||
        "",
      grade:
        payload.grade ||
        bundle.grade ||
        payload.lesson?.grade ||
        "",
    },
  };
}

export async function loadImportScopedRuntimeState(client, payload = {}, snapshotKey = "default") {
  const scope = extractImportScope(payload);
  return loadLessonScopedRuntimeState(
    client,
    {
      lessonId: scope.lessonId,
      bundleId: scope.bundleId,
      catalogScope: scope.catalogScope,
      includeArtifacts: false,
      includeTaskProjections: false,
      includePublications: false,
      includeReviewTasks: false,
      includeQualityEvaluations: false,
    },
    snapshotKey
  );
}

export async function loadReviewTaskScopedRuntimeState(
  client,
  reviewTaskId,
  snapshotKey = "default"
) {
  const state = await buildScopedStateShell(client, snapshotKey);
  state.reviewTasks = await selectStateRows(
    client,
    "reviewTasks",
    `where review_task_id = $1`,
    [reviewTaskId]
  );
  const reviewTask = state.reviewTasks[0] || null;
  if (!reviewTask) {
    return state;
  }
  if (reviewTask.target_type === "lesson_revision") {
    state.lessonRevisions = await selectStateRows(
      client,
      "lessonRevisions",
      `where lesson_revision_id = $1`,
      [reviewTask.target_revision_id]
    );
  } else if (reviewTask.target_type === "task_revision") {
    state.taskRevisions = await selectStateRows(
      client,
      "taskRevisions",
      `where task_revision_id = $1`,
      [reviewTask.target_revision_id]
    );
  }
  return state;
}

export async function loadPublishScopedRuntimeState(
  client,
  lessonId,
  snapshotKey = "default"
) {
  return loadLessonScopedRuntimeState(
    client,
    {
      lessonId,
      includeImports: false,
      includeReviewTasks: false,
      includeQualityEvaluations: false,
    },
    snapshotKey
  );
}

export async function loadQuestionBankScopedRuntimeState(
  client,
  payload = {},
  snapshotKey = "default"
) {
  const state = await buildScopedStateShell(client, snapshotKey);
  if (payload.taskProjectionId) {
    state.taskProjections = await selectStateRows(
      client,
      "taskProjections",
      `where task_projection_id = $1`,
      [payload.taskProjectionId]
    );
    const projection = state.taskProjections[0] || null;
    if (projection?.lesson_id) {
      state.lessons = await selectStateRows(
        client,
        "lessons",
        `where lesson_id = $1`,
        [projection.lesson_id]
      );
      state.publications = await selectStateRows(
        client,
        "publications",
        `where lesson_id = $1 order by created_at asc`,
        [projection.lesson_id]
      );
    }
  }
  if (payload.questionBankItemId) {
    state.questionBankItems = await selectStateRows(
      client,
      "questionBankItems",
      `where question_bank_item_id = $1`,
      [payload.questionBankItemId]
    );
  }
  return state;
}

export async function loadCreateMaterialBuildScopedRuntimeState(
  client,
  payload = {},
  snapshotKey = "default"
) {
  const state = await buildScopedStateShell(client, snapshotKey);
  if (payload.lessonId) {
    state.lessons = await selectStateRows(
      client,
      "lessons",
      `where lesson_id = $1`,
      [payload.lessonId]
    );
  }
  return state;
}

export async function loadMaterialItemsScopedRuntimeState(
  client,
  materialBuildId,
  payload = {},
  snapshotKey = "default"
) {
  const state = await buildScopedStateShell(client, snapshotKey);
  state.materialBuilds = await selectStateRows(
    client,
    "materialBuilds",
    `where material_build_id = $1`,
    [materialBuildId]
  );
  const revisionIds = uniqueStrings(
    (payload.items || []).map((item) => item.questionBankItemRevisionId)
  );
  if (revisionIds.length) {
    state.questionBankItemRevisions = await selectStateRows(
      client,
      "questionBankItemRevisions",
      `where question_bank_item_revision_id = any($1::text[])`,
      [revisionIds]
    );
    const itemIds = uniqueStrings(
      state.questionBankItemRevisions.map((item) => item.question_bank_item_id)
    );
    if (itemIds.length) {
      state.questionBankItems = await selectStateRows(
        client,
        "questionBankItems",
        `where question_bank_item_id = any($1::text[])`,
        [itemIds]
      );
    }
  }
  return state;
}

export async function loadMaterialExportScopedRuntimeState(
  client,
  materialBuildId,
  snapshotKey = "default"
) {
  const state = await buildScopedStateShell(client, snapshotKey);
  state.materialBuilds = await selectStateRows(
    client,
    "materialBuilds",
    `where material_build_id = $1`,
    [materialBuildId]
  );
  state.materialItems = await selectStateRows(
    client,
    "materialItems",
    `where material_build_id = $1 order by sort_index asc, created_at asc`,
    [materialBuildId]
  );
  const materialBuild = state.materialBuilds[0] || null;
  if (materialBuild?.lesson_id) {
    state.lessons = await selectStateRows(
      client,
      "lessons",
      `where lesson_id = $1`,
      [materialBuild.lesson_id]
    );
  }
  return state;
}

export async function loadRegisterExportRunScopedRuntimeState(
  client,
  lessonId,
  snapshotKey = "default"
) {
  const state = await buildScopedStateShell(client, snapshotKey);
  state.lessons = await selectStateRows(
    client,
    "lessons",
    `where lesson_id = $1`,
    [lessonId]
  );
  state.publications = await selectStateRows(
    client,
    "publications",
    `where lesson_id = $1 order by created_at asc`,
    [lessonId]
  );
  state.artifacts = await selectStateRows(
    client,
    "artifacts",
    `where coalesce(summary_json->>'lesson_id', '') = $1 order by created_at asc`,
    [lessonId]
  );
  return state;
}
