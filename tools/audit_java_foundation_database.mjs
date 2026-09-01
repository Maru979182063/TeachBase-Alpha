import fs from "node:fs/promises";
import path from "node:path";

import {
  createHarness,
  workspaceRoot,
} from "../tests/helpers/runtime_testkit.mjs";

const REPORT_DATE = "20260831";
const reportDirectory = path.join(workspaceRoot, "docs", "reports");
const jsonPath = path.join(reportDirectory, `java_foundation_database_inventory_${REPORT_DATE}.json`);
const markdownPath = path.join(reportDirectory, `java_foundation_database_inventory_${REPORT_DATE}.md`);

function quoteIdentifier(value) {
  return `"${String(value).replaceAll('"', '""')}"`;
}

function stableSort(items, selector) {
  return [...items].sort((left, right) => selector(left).localeCompare(selector(right)));
}

async function exactRowCount(harness, connectionString, tableName) {
  const result = await harness.queryDatabase(
    connectionString,
    `select count(*)::bigint as count from public.${quoteIdentifier(tableName)}`
  );
  return Number(result.rows[0]?.count || 0);
}

async function profileJsonColumn(harness, connectionString, tableName, columnName) {
  const table = quoteIdentifier(tableName);
  const column = quoteIdentifier(columnName);
  const summary = await harness.queryDatabase(
    connectionString,
    `select coalesce(sum(type_count), 0)::bigint as non_null_count,
            coalesce(jsonb_object_agg(value_type, type_count) filter (where value_type is not null), '{}'::jsonb) as value_types
       from (
         select jsonb_typeof(${column}::jsonb) as value_type, count(*)::bigint as type_count
           from public.${table}
          where ${column} is not null
          group by jsonb_typeof(${column}::jsonb)
       ) profile`
  );
  const keys = await harness.queryDatabase(
    connectionString,
    `select key, count(*)::bigint as occurrences
       from public.${table}
       cross join lateral jsonb_object_keys(
         case when jsonb_typeof(${column}::jsonb) = 'object' then ${column}::jsonb else '{}'::jsonb end
       ) as key
      where ${column} is not null
      group by key
      order by occurrences desc, key
      limit 50`
  );
  return {
    table: tableName,
    column: columnName,
    nonNullCount: Number(summary.rows[0]?.non_null_count || 0),
    valueTypes: summary.rows[0]?.value_types || {},
    topLevelKeys: keys.rows.map((row) => ({
      key: row.key,
      occurrences: Number(row.occurrences),
    })),
  };
}

function renderMarkdown(report) {
  const populated = report.tables.filter((table) => table.rowCount > 0);
  const jsonColumns = report.jsonProfiles.filter((profile) => profile.nonNullCount > 0);
  const missingFk = report.relationAudit.idLikeColumnsWithoutForeignKey;
  const lines = [
    "# Java Foundation Database Inventory",
    "",
    `- Baseline: \`${report.baseline.sha}\``,
    `- PostgreSQL: \`${report.database.postgresVersion}\``,
    `- Applied migration: \`${report.database.migrationVersion}\``,
    `- Public tables: **${report.summary.tableCount}**`,
    `- Populated by deterministic startup fixtures: **${report.summary.populatedTableCount}**`,
    `- Foreign keys: **${report.summary.foreignKeyCount}**`,
    `- JSON/JSONB columns: **${report.summary.jsonColumnCount}**`,
    "",
    "The inventory was produced from an isolated, disposable PostgreSQL database. It does not use a developer database or a machine-specific path as an input contract.",
    "",
    "## Populated Tables",
    "",
    "| Table | Rows | Columns | Primary key | Foreign keys |",
    "|---|---:|---:|---|---:|",
    ...populated.map((table) =>
      `| \`${table.name}\` | ${table.rowCount} | ${table.columnCount} | ${table.primaryKey.join(", ") || "-"} | ${table.foreignKeyCount} |`
    ),
    "",
    "## Empty Tables",
    "",
    report.tables.filter((table) => table.rowCount === 0).map((table) => `\`${table.name}\``).join(", ") || "None",
    "",
    "## JSON Payloads With Data",
    "",
    ...jsonColumns.map((profile) =>
      `- \`${profile.table}.${profile.column}\`: ${profile.nonNullCount} values; keys: ${profile.topLevelKeys.map((item) => `\`${item.key}\``).join(", ") || "no object keys"}`
    ),
    "",
    "## Relationship Risk",
    "",
    `There are **${missingFk.length}** identifier-like columns without a database foreign key. This is a heuristic list, not proof that every column needs an FK. It is the main input for the field mapping review.`,
    "",
    ...missingFk.map((item) => `- \`${item.table}.${item.column}\``),
    "",
  ];
  return `${lines.join("\n")}\n`;
}

async function main() {
  const harness = await createHarness({ runId: "java_foundation_database_inventory" });
  try {
    const server = await harness.startPostgresServer("java_foundation_inventory_test");
    const connectionString = server.database.connectionString;
    const health = await server.request("/health");

    const tableRows = await harness.queryDatabase(
      connectionString,
      `select table_name
         from information_schema.tables
        where table_schema = 'public' and table_type = 'BASE TABLE'
        order by table_name`
    );
    const columnRows = await harness.queryDatabase(
      connectionString,
      `select table_name, column_name, ordinal_position, data_type, udt_name,
              is_nullable, column_default
         from information_schema.columns
        where table_schema = 'public'
        order by table_name, ordinal_position`
    );
    const constraintRows = await harness.queryDatabase(
      connectionString,
      `select c.conname as name,
              c.contype as type,
              source.relname as table_name,
              target.relname as referenced_table,
              pg_get_constraintdef(c.oid, true) as definition
         from pg_constraint c
         join pg_class source on source.oid = c.conrelid
         join pg_namespace n on n.oid = source.relnamespace
         left join pg_class target on target.oid = c.confrelid
        where n.nspname = 'public'
        order by source.relname, c.contype, c.conname`
    );
    const indexRows = await harness.queryDatabase(
      connectionString,
      `select tablename as table_name, indexname as name, indexdef as definition
         from pg_indexes
        where schemaname = 'public'
        order by tablename, indexname`
    );

    const constraints = constraintRows.rows.map((row) => ({
      name: row.name,
      type: row.type,
      table: row.table_name,
      referencedTable: row.referenced_table || null,
      definition: row.definition,
    }));
    const columns = columnRows.rows.map((row) => ({
      table: row.table_name,
      name: row.column_name,
      position: Number(row.ordinal_position),
      dataType: row.data_type,
      databaseType: row.udt_name,
      nullable: row.is_nullable === "YES",
      default: row.column_default || null,
    }));

    const tables = [];
    for (const row of tableRows.rows) {
      const name = row.table_name;
      const tableColumns = columns.filter((column) => column.table === name);
      const tableConstraints = constraints.filter((constraint) => constraint.table === name);
      const primaryKeyDefinition = tableConstraints.find((constraint) => constraint.type === "p")?.definition || "";
      const primaryKey = primaryKeyDefinition.match(/PRIMARY KEY \((.+)\)/i)?.[1]
        ?.split(",")
        .map((item) => item.trim().replaceAll('"', "")) || [];
      tables.push({
        name,
        rowCount: await exactRowCount(harness, connectionString, name),
        columnCount: tableColumns.length,
        primaryKey,
        foreignKeyCount: tableConstraints.filter((constraint) => constraint.type === "f").length,
        columns: tableColumns,
      });
    }

    const jsonColumns = columns.filter((column) => ["json", "jsonb"].includes(column.dataType));
    const jsonProfiles = [];
    for (const column of jsonColumns) {
      jsonProfiles.push(await profileJsonColumn(harness, connectionString, column.table, column.name));
    }

    const fkDefinitions = new Set(
      constraints
        .filter((constraint) => constraint.type === "f")
        .flatMap((constraint) => constraint.definition.match(/FOREIGN KEY \(([^)]+)\)/i)?.[1]?.split(",") || [])
        .map((column) => `${column.trim().replaceAll('"', "")}`)
    );
    const idLikeColumnsWithoutForeignKey = columns
      .filter((column) => /(^id$|_id$|_ids$|_ref$)/.test(column.name))
      .filter((column) => !tables.find((table) => table.name === column.table)?.primaryKey.includes(column.name))
      .filter((column) => !fkDefinitions.has(column.name))
      .map((column) => ({ table: column.table, column: column.name, dataType: column.dataType }));

    const report = {
      reportVersion: "java-foundation-database-inventory-v1",
      generatedAt: new Date().toISOString(),
      baseline: {
        branch: "backend/java-modulith-foundation-survey",
        sha: "8ca1703700c22d6e13ee3b26e2b902c8d9c5a309",
      },
      database: {
        source: "isolated-embedded-postgres-with-deterministic-runtime-fixtures",
        postgresVersion: harness.postgresCluster?.version || null,
        migrationVersion: health.data?.storeHealth?.migrationVersion || null,
        runtimeMode: health.data?.runtimeMode || null,
      },
      summary: {
        tableCount: tables.length,
        populatedTableCount: tables.filter((table) => table.rowCount > 0).length,
        columnCount: columns.length,
        constraintCount: constraints.length,
        foreignKeyCount: constraints.filter((constraint) => constraint.type === "f").length,
        indexCount: indexRows.rows.length,
        jsonColumnCount: jsonColumns.length,
      },
      tables: stableSort(tables, (table) => table.name),
      constraints,
      indexes: indexRows.rows.map((row) => ({
        table: row.table_name,
        name: row.name,
        definition: row.definition,
      })),
      jsonProfiles,
      relationAudit: {
        method: "heuristic identifier-like columns not covered by any foreign-key column name",
        idLikeColumnsWithoutForeignKey,
      },
      limitations: [
        "The database is populated by deterministic repository fixtures, not a developer or production database.",
        "Row counts prove exercised schema coverage only; they do not estimate production volume.",
        "The identifier-like column check is a review queue and may contain intentional denormalized fields.",
      ],
    };

    await fs.mkdir(reportDirectory, { recursive: true });
    await fs.writeFile(jsonPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    await fs.writeFile(markdownPath, renderMarkdown(report), "utf8");
    process.stdout.write(`${JSON.stringify({ ok: true, tableCount: report.summary.tableCount, populatedTableCount: report.summary.populatedTableCount, jsonPath: path.relative(workspaceRoot, jsonPath), markdownPath: path.relative(workspaceRoot, markdownPath) }, null, 2)}\n`);
  } finally {
    await harness.dispose();
  }
}

await main();
