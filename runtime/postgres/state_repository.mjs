/**
 * 用途：
 * - 负责在 Postgres 表中读取、播种、归一化和替换运行时主干状态。
 * - 表结构变化时，要同步更新 state_table_configs.mjs 和存储契约测试。
 */

import {
  buildSeedState,
  computeContentHash,
  normalizeState,
} from "../../tools/runtime_backbone_store.mjs";
import {
  runtimeMetadataConfig,
  stateTableConfigs,
} from "./state_table_configs.mjs";

function cloneState(state) {
  return JSON.parse(JSON.stringify(state));
}

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

function defaultRuntimeMeta(existing = {}) {
  const now = new Date().toISOString();
  return {
    generatedAt: existing.generatedAt || now,
    updatedAt: existing.updatedAt || existing.generatedAt || now,
    source: existing.source || "postgres_normalized_tables",
  };
}

function buildStateShell(meta = {}) {
  return normalizeState({
    meta: defaultRuntimeMeta(meta),
  });
}

function buildNormalizedRows(rows, columns) {
  return rows.map((row) => {
    const normalized = {};
    for (const column of columns) {
      normalized[column] = row?.[column] ?? null;
    }
    return normalized;
  });
}

function buildStateRows(state, config, columns = config.writeColumns) {
  return buildNormalizedRows(state?.[config.stateKey] || [], columns);
}

function sortRows(rows, primaryKey) {
  return [...rows].sort((left, right) =>
    String(left?.[primaryKey] ?? "").localeCompare(String(right?.[primaryKey] ?? ""))
  );
}

async function selectTableRows(client, config, columns = config.readColumns) {
  const result = await client.query(
    `
      select to_jsonb(source_row) as row_json
      from (
        select ${columns.map(buildSelectExpression).join(", ")}
        from ${quoteIdent(config.table)}
        order by ${quoteIdent(config.primaryKey)}
      ) as source_row
    `
  );
  return result.rows.map((row) => row.row_json);
}

async function upsertRows(client, config, rows) {
  if (!rows.length) {
    return;
  }

  const columns = config.writeColumns;
  const columnSql = columns.map(quoteIdent).join(", ");
  const values = [];
  const valueSql = rows
    .map((row, rowIndex) => {
      const placeholders = columns.map((column, columnIndex) => {
        values.push(row[column] ?? null);
        return `$${rowIndex * columns.length + columnIndex + 1}`;
      });
      return `(${placeholders.join(", ")})`;
    })
    .join(", ");
  const updateSql = columns
    .filter((column) => column !== config.primaryKey)
    .map((column) => `${quoteIdent(column)} = excluded.${quoteIdent(column)}`)
    .join(", ");

  await client.query(
    `
      insert into ${quoteIdent(config.table)} (${columnSql})
      values ${valueSql}
      on conflict (${quoteIdent(config.primaryKey)})
      do update set ${updateSql}
    `,
    values
  );
}

async function insertRows(client, config, rows) {
  if (!rows.length) {
    return;
  }

  const columns = config.writeColumns;
  const columnSql = columns.map(quoteIdent).join(", ");
  const values = [];
  const valueSql = rows
    .map((row, rowIndex) => {
      const placeholders = columns.map((column, columnIndex) => {
        values.push(row[column] ?? null);
        return `$${rowIndex * columns.length + columnIndex + 1}`;
      });
      return `(${placeholders.join(", ")})`;
    })
    .join(", ");

  await client.query(
    `
      insert into ${quoteIdent(config.table)} (${columnSql})
      values ${valueSql}
    `,
    values
  );
}

async function deleteRowsByPrimaryKey(client, config, primaryKeys) {
  if (!primaryKeys.length) {
    return;
  }

  await client.query(
    `
      delete from ${quoteIdent(config.table)}
      where ${quoteIdent(config.primaryKey)} = any($1::text[])
    `,
    [primaryKeys]
  );
}

async function loadRuntimeMetadata(client, snapshotKey) {
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
  if (!result.rows.length) {
    return null;
  }
  const row = result.rows[0].row_json || {};
  return {
    generatedAt: row.generated_at || null,
    updatedAt: row.updated_at || null,
    source: row.source || null,
  };
}

async function upsertRuntimeMetadata(client, snapshotKey, meta) {
  const normalizedMeta = defaultRuntimeMeta(meta);
  await upsertRows(client, runtimeMetadataConfig, [
    {
      snapshot_key: snapshotKey,
      generated_at: normalizedMeta.generatedAt,
      updated_at: normalizedMeta.updatedAt,
      source: normalizedMeta.source,
    },
  ]);
  return normalizedMeta;
}

function buildRowMap(rows, config) {
  return new Map(
    rows.map((row) => [String(row?.[config.primaryKey] ?? ""), row])
  );
}

/**
 * 根据两个归一化运行时状态计算表级插入、更新和删除。
 * 这样既能增量持久化，又让调用方继续以完整状态快照思考。
 */
function buildTableDiff(config, previousState, nextState) {
  const previousRows = buildStateRows(previousState, config);
  const nextRows = buildStateRows(nextState, config);
  const previousMap = buildRowMap(previousRows, config);
  const nextMap = buildRowMap(nextRows, config);
  const upserts = [];
  const deletes = [];

  for (const [primaryKey, nextRow] of nextMap.entries()) {
    const previousRow = previousMap.get(primaryKey);
    if (!previousRow || computeContentHash(previousRow) !== computeContentHash(nextRow)) {
      upserts.push(nextRow);
    }
  }
  for (const primaryKey of previousMap.keys()) {
    if (!nextMap.has(primaryKey)) {
      deletes.push(primaryKey);
    }
  }

  return {
    upserts,
    deletes,
  };
}

export function cloneRuntimeState(state) {
  return cloneState(state);
}

export async function loadRuntimeState(client, snapshotKey = "default") {
  const state = buildStateShell(await loadRuntimeMetadata(client, snapshotKey));
  for (const config of stateTableConfigs) {
    state[config.stateKey] = await selectTableRows(client, config);
  }
  return normalizeState(state);
}

export async function ensureSeedRuntimeState(client, snapshotKey = "default") {
  const result = await client.query("select exists(select 1 from lesson limit 1) as has_rows");
  if (result.rows[0]?.has_rows) {
    return {
      seeded: false,
    };
  }

  const seedState = normalizeState(buildSeedState());
  seedState.meta = {
    ...defaultRuntimeMeta(seedState.meta),
    source: seedState.meta?.source || "workbench_data_seed",
  };
  await replaceRuntimeState(client, seedState, snapshotKey);
  return {
    seeded: true,
    state: seedState,
  };
}

/**
 * 在调用方拥有的事务中应用表差异，完成一次状态迁移持久化。
 * 事务边界由调用方负责，以保证多步骤工作流保持原子性。
 */
export async function persistRuntimeState(client, previousState, nextState, snapshotKey = "default") {
  const normalizedPrevious = normalizeState(previousState || buildStateShell());
  const normalizedNext = normalizeState(nextState || buildStateShell());
  normalizedNext.meta = defaultRuntimeMeta(normalizedNext.meta);

  const tableStats = [];
  for (const config of stateTableConfigs) {
    const diff = buildTableDiff(config, normalizedPrevious, normalizedNext);
    await upsertRows(client, config, diff.upserts);
    await deleteRowsByPrimaryKey(client, config, diff.deletes);
    tableStats.push({
      table: config.table,
      upserts: diff.upserts.length,
      deletes: diff.deletes.length,
    });
  }

  await upsertRuntimeMetadata(client, snapshotKey, normalizedNext.meta);
  return {
    tableStats,
  };
}

export async function reseedRuntimeState(client, snapshotKey = "default") {
  const seedState = normalizeState(buildSeedState());
  seedState.meta = {
    ...defaultRuntimeMeta(seedState.meta),
    source: seedState.meta?.source || "workbench_data_seed",
  };
  const persistence = await replaceRuntimeState(client, seedState, snapshotKey);
  return {
    state: seedState,
    persistence,
  };
}

export async function replaceRuntimeState(client, nextState, snapshotKey = "default") {
  const normalizedNext = normalizeState(nextState || buildStateShell());
  normalizedNext.meta = defaultRuntimeMeta(normalizedNext.meta);

  // Seed/bootstrap is the only place we allow bulk table replacement because
  // it is a one-shot environment reset rather than a normal business write path.
  await client.query(
    `truncate table ${[runtimeMetadataConfig.table, ...stateTableConfigs.map((config) => config.table)]
      .map(quoteIdent)
      .join(", ")}`
  );
  for (const config of stateTableConfigs) {
    await insertRows(client, config, buildStateRows(normalizedNext, config));
  }
  await upsertRuntimeMetadata(client, snapshotKey, normalizedNext.meta);
  return {
    tableStats: stateTableConfigs.map((config) => ({
      table: config.table,
      upserts: (normalizedNext?.[config.stateKey] || []).length,
      deletes: 0,
    })),
  };
}

/**
 * 根据内存状态快照生成预期行数。
 * 就绪检查会把它和在线数据库报告对比，用来捕获投影漂移。
 */
export function buildExpectedTableReport(state) {
  const report = {};
  for (const config of stateTableConfigs) {
    const rows = sortRows(buildStateRows(state, config, config.hashColumns), config.primaryKey);
    report[config.table] = {
      count: rows.length,
      hash: computeContentHash(rows),
    };
  }
  return report;
}

export async function buildActualTableReport(client) {
  const report = {};
  for (const config of stateTableConfigs) {
    const rows = sortRows(
      buildNormalizedRows(await selectTableRows(client, config, config.hashColumns), config.hashColumns),
      config.primaryKey
    );
    report[config.table] = {
      count: rows.length,
      hash: computeContentHash(rows),
    };
  }
  return report;
}
