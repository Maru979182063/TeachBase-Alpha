/**
 * 用途：
 * - 存放备份和导出流程使用的轻量级快照元数据。
 * - 这个模块不负责完整运行时状态表，只记录快照相关的辅助数据。
 */

import { computeContentHash } from "../../tools/runtime_backbone_store.mjs";

export async function readSnapshotInfo(client, snapshotKey) {
  const result = await client.query(
    `
      select snapshot_version, snapshot_content_hash, updated_at
      from runtime_state_snapshot
      where snapshot_key = $1
    `,
    [snapshotKey]
  );
  if (!result.rows.length) {
    return {
      present: false,
      snapshotVersion: 0,
      snapshotContentHash: null,
      updatedAt: null,
    };
  }
  const row = result.rows[0];
  return {
    present: true,
    snapshotVersion: Number(row.snapshot_version || 0),
    snapshotContentHash: row.snapshot_content_hash || null,
    updatedAt: row.updated_at ? new Date(row.updated_at).toISOString() : null,
  };
}

export async function writeSnapshotBestEffort(pool, snapshotKey, state, enabled = false) {
  if (!enabled) {
    return {
      status: "disabled",
    };
  }

  try {
    const snapshotInfo = await readSnapshotInfo(pool, snapshotKey);
    const nextSnapshotVersion = Number(snapshotInfo.snapshotVersion || 0) + 1;
    const snapshotContentHash = computeContentHash(state);
    await pool.query(
      `
        insert into runtime_state_snapshot (
          snapshot_key,
          snapshot_json,
          snapshot_version,
          snapshot_content_hash,
          updated_at
        )
        values ($1, $2::jsonb, $3, $4, now())
        on conflict (snapshot_key)
        do update
        set snapshot_json = excluded.snapshot_json,
            snapshot_version = excluded.snapshot_version,
            snapshot_content_hash = excluded.snapshot_content_hash,
            updated_at = excluded.updated_at
      `,
      [snapshotKey, JSON.stringify(state), nextSnapshotVersion, snapshotContentHash]
    );
    return {
      status: "ok",
      snapshotVersion: nextSnapshotVersion,
      snapshotContentHash,
    };
  } catch (error) {
    return {
      status: "failed",
      error: String(error?.message || error),
    };
  }
}
