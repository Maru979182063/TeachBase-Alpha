# G4 V009 Migration 与回滚 Runbook

## 1. 部署前

1. 停止批量 Release Seed 和讲义导入写入；G4 不要求停止普通读取。
2. 备份数据库，并记录当前 Flyway 版本应为 `008`。
3. 在候选制品上运行 `npm run test:g4-v009-migration`，同时覆盖空库 V001→V009 和真实形状 V008→V009。
4. 确认应用制品与 V009 同批部署。V009 改变 `question_source_link` 的唯一合同，禁止将数据库迁到 V009 后长期运行 V008 writer。

## 2. 前向迁移

V009 会：

- 为来源关系增加 workspace/document 组合约束；
- 为旧 question source 行回填稳定 legacy evidence key，并允许一个 revision 有多条证据；
- 增加 standard module、review/taxonomy/source/file 关系；
- 增加 handout edition/composition/occurrence；
- 增加 editor revision artifact 强引用与不可变 trigger。

V009 不更新或删除 `question_revision`、`editor_revision`、`editor_working_draft`、`editor_snapshot` 的既有内容。

执行由应用启动时 Flyway 完成。验证：

```text
npm run test:g4-v009-migration
npm run build:java-foundation
npm run test:g4-handout-live
```

## 3. 迁移后核验

- `flyway_schema_history` 最新成功版本为 `009`。
- 旧 revision、working draft 和 snapshot 的 ID/hash/JSON 不变。
- 旧 question source 行拥有 `legacy:<uuid>` evidence key。
- 同一个 question revision 可以插入两个不同 evidence key。
- composition 同 payload 并发创建只有一个 creator。
- 不可变 module/occurrence 的直接 UPDATE 被 PostgreSQL 拒绝。

## 4. 回滚

V009 是前向、非破坏性业务迁移，但来源 writer 合同已经升级。优先回滚方式是：

1. 关闭 G4 HTTP 流量和 Release Seed 写入；
2. 保留 V009 表与数据；
3. 部署兼容 V009 的上一候选制品或修复版，不直接部署只理解 V008 唯一键的旧 writer；
4. 继续使用旧 editor/master JSON 读取路径，G4 composition 暂不参与业务读取；
5. 修复后重新运行 migration/live gate 再开放写入。

不要对已写入的不可变 revision、occurrence 或 artifact link 做原地回写。若必须物理降级到 V008，应在停写、完整备份和逐表导出 G4 数据后，由人工审核的反向迁移处理；这不是自动运行路径。

## 5. 失败处置

- 外键失败：检查 workspace、source document、source region、file version 是否属于同一作用域。
- composition conflict：比较 canonical content hash；不得覆盖原 revision。
- artifact conflict：同 `artifactKey` 必须对应相同 role/file/source/metadata；改用新的、稳定的 artifact key。
- renderer 回归失败：保留 G4 数据，单独处理导出适配器；不要把存储 migration 回滚当作渲染修复。
