# Backup Restore Runbook

更新时间：2026-06-23

## 当前状态

当前状态：`PARTIAL_PASS`

当前已完成：

- 本机 `pg_dump` / `pg_restore` 已可用
- `tests/backup-restore/runtime_backup_restore.mjs` 已通过
- 已完成：
  - `pg_dump`
  - 恢复到全新数据库
  - 恢复前后关键表计数核对

当前仍未完成：

- `N05-N16` 的更深恢复矩阵
- 恢复后完整搜索 / export / artifact 文件对账
- 实测 RTO 的正式记录

## 目标

对 runtime backbone 的 PostgreSQL 数据执行：

1. 逻辑备份
2. 恢复到全新数据库
3. 恢复后核对关键事实
4. 恢复后再次执行服务健康检查与检索冒烟

## 目标 RPO / RTO

- 建议 RPO：`<= 15 分钟`
- 建议 RTO：`<= 60 分钟`

当前说明：

- 以上是建议目标，不是本轮实测值
- 本轮因缺少工具链，`实际 RTO 未测得`

## 建议备份频率

- 主库逻辑备份：每 15 分钟增量或 WAL 级连续归档
- 每日全量逻辑备份：至少 1 次
- 周级归档：至少 1 份

## 建议保留周期

- 15 分钟级短期备份：保留 48 小时
- 每日备份：保留 14 天
- 周备份：保留 8 周

## 执行前提

必须满足：

1. 具备 `pg_dump` / `pg_restore`
2. 使用专用恢复验证库，数据库名必须包含 `test` / `ci` / `integration`
3. 不允许对疑似生产库执行清库恢复演练
4. 恢复前后都要记录：
   - host
   - port
   - database name
   - PostgreSQL version
5. 不记录密码和完整明文连接串

## 建议命令

当前测试脚本：

- `npm run test:backup-restore`

脚本会尝试：

1. 启动真实 PostgreSQL 验证环境
2. 导入一份已发布 lesson 数据
3. 使用 `pg_dump` 生成备份
4. 恢复到全新数据库
5. 对比以下表的记录数：
   - `lesson`
   - `lesson_revision`
   - `task_projection`
   - `publication`
   - `artifact`

## 恢复成功判定

当前已验证通过的最低条件：

1. 表计数一致
2. `published_revision_id` 一致
3. publication 历史可查
4. 基础恢复到全新数据库成功

完整恢复通过仍建议继续补测：

1. task projection 可正常搜索
2. 服务 `/health` 为 healthy
3. 一致性检查返回 `ok`
4. material / export / artifact 文件对账

## 建议人工核验项

恢复完成后，额外人工确认：

1. 讲义详情可读
2. 已发布 revision 正确
3. question bank revision 仍可追溯
4. material item 没有漂移
5. component revision 与 patch 历史仍在

## 谁来执行

建议责任人：

- 主执行：后端负责人 / DBA
- 见证与复核：研发负责人

## 下一步

下一步建议：

1. 把 `N05-N16` 补成自动化或半自动恢复清单
2. 在测试机或 VPS 上记录正式 RTO
3. 补齐 artifact 文件级对账
