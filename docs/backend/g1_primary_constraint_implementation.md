# G1 主标签约束实施说明

本轮用户已确认：同一题目修订＋同一 taxonomy 版本最多一个主标签。跨版本语义后续确定；不将 taxonomy_key、树内分支或节点名称推断为教学维度。

## 数据库与 HTTP 行为

追加迁移 [V009](../../backend/teachbase-server/src/main/resources/db/migration/V009__single_primary_per_taxonomy_version.sql)，V001—V008 与基线 Git 内容逐字核对保持一致。

迁移在事务内锁定标签关联表，扫描同 revision/version 下的多主标签。发现冲突立即以 `taxonomy_primary_conflicts_before_v009` 中止；异常 detail 给出前 50 组精确 ID，全量清单由独立只读扫描工具生成。迁移不选择胜者、不降级、不删除任何记录。没有冲突时建立：

```sql
create unique index uq_question_primary_per_taxonomy_version
on teachbase_app.question_taxonomy_link(question_revision_id, taxonomy_version_id)
where relation_type = 'primary';
```

同修订 ID 与版本 ID 均有原有工作空间外键约束，不依赖 Java 调用方遵守唯一性。直接 SQL 的插入和升级为 primary 同样受约束。

Java 使用数据库 `ON CONFLICT DO NOTHING` 仲裁，再查询区分同绑定重放和另一主标签冲突。避免在 PostgreSQL 唯一键异常已使事务失败后继续查询。

| 请求 | 实际行为 |
| --- | --- |
| 首次绑定主标签 | 200，建立关联 |
| 同绑定再次请求 | 200，返回同一关联 ID |
| 同 revision/version 的另一个主标签 | 409，detail=`taxonomy_primary_conflict`，保留旧关联 |
| 两个不同主标签并发 | 一个 200、一个 409；最终只有一个 primary |
| 多个 secondary | 允许，重复绑定仍幂等 |
| 新修订在同版本绑定 primary | 允许，旧修订关联保持 |
| 新 taxonomy 版本绑定 primary | 允许，旧版本历史保留 |
| 向已退休版本新增绑定 | 沿用已有 409 `taxonomy_version_not_active` |

此处没有实现主标签切换、旧主降级/删除或跨版本标签迁移。旧的统一标签/搜索设计门禁不能因这项有限约束通过而整体标为已关闭。

## 数据扫描与演练

只读扫描命令：

```text
node tools/scan_taxonomy_primary_conflicts.mjs --source-data-root D:/Projects/TeachBase-Alpha-local-data/candidate-ingestion-20260904 --out artifacts/ci/g0-g1/source-conflicts-after.json
```

独立隔离门禁：

```text
node tools/run_g1_primary_constraint_gate.mjs --source-data-root D:/Projects/TeachBase-Alpha-local-data/candidate-ingestion-20260904 --out-dir artifacts/ci/g0-g1/g1-live-final
```

扫描工具使用显式只读事务；完整冲突 SQL 位于 `tools/sql/scan_taxonomy_primary_conflicts.sql`。真实库扫描前后均为：52 个修订，52 待审核，0 已批准，0 taxonomy 版本/节点/关联，0 冲突。无标签不能证明教学标签质量，只能说明这份库没有存量主标签冲突。

隔离测试额外构造两条冲突关联：扫描发现 1 组、2 个 primary；迁移中止后保留两条记录，未留下部分索引。干净的真实库副本由 Flyway 正常迁移到 V009，题目/修订/审核/标签内容指纹不变。专门门禁 10 项通过，SQLSTATE 23505 和 HTTP 409 均有实际结果。

第一次专门门禁因临时测试库名称不符合现有安全检查而中止；已改为带 `_test` 的明确测试库名，保持安全检查不变。首次报告保留在本地 `g1-live`，最终报告在 `g1-live-final`，不将首次中止隐藏成通过。

## 部署与回退边界

本轮 V009 仅在隔离数据库应用，原候选库仍为 V001—V008。真实库迁移未执行。

未来迁移必须先扫描完整冲突、留存恢复点，并安排表锁窗口。本阶段验证了正确性，未开展 G3 的大容量锁等待或恢复 SLA 验收。存在冲突时先提交人工处理方案，不自动修复真实数据。

回退应用时保留数据库唯一索引；回到不识别该冲突的旧服务可能出现非 409 错误，因此应保留这段异常映射或暂停标签写入，不能通过删除约束恢复旧的双主标签行为。尚未运行 G2—G5，也不新增用于绕过阶段门禁的后台任务。
