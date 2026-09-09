# G5 Canonical Content Import Contract & Recovery 设计审计

状态：`G5_DESIGN_APPROVED_FOR_IMPLEMENTATION`

基线：`backend/g4-handout-content-asset-foundation@cf64da9aac48c2a086c33a305a933eecfe1abc51`

## 1. 现状结论

V001-V009 已分别建立 workspace/audit、file/source、question/editor、检索与题篮、Review/taxonomy、Release Seed、成员教学范围、WP-01 working draft 和 G4 内容资产/composition。缺口不是再建一套资产表，而是缺少跨资产的唯一正式收货合同、package ledger、显式依赖计划和可恢复执行器。

不存在必须修改 G4 核心语义的冲突，可以进入 G5。G5 必须作为独立 `canonicalimport` 模块编排各领域公开 API，不能直接把 Release Seed 扩成万能 importer，也不能让 Python/Node 绕过 Java 写 canonical PostgreSQL 表。

## 2. 现有能力复用

| 领域 | 可复用能力 | G5 缺口 |
|---|---|---|
| File | SHA-256 幂等 file version、portable storage key | 按精确 fileVersionId 做 package 预检 |
| Source | external source/region key 幂等注册 | package logical key 到数据库 ID 的 operation 映射 |
| Question | stable source identity、content hash revision dedup、source evidence | 单项 gateway 编排与 ledger target 记录 |
| Standard Module | moduleKey、不可变 revision、source/file/taxonomy、Review | 面向 importer 的公开 gateway |
| Editor | WP-01 draft、显式冻结 revision、snapshot | 稳定 import document key 和无 snapshot 的受控 frozen revision gateway |
| Handout | immutable edition/composition/occurrence、teacher projection | 面向 importer 的公开 gateway与 frozen payload 重放 |
| Review/Taxonomy | 精确 revision 引用 | review intent，不做自动批准或风险路由 |
| Release Seed | 文件包验证、lease、checkpoint、resume、verify | 只面向首发人工审核题目，question-centric 且会自动完成 Review，不可作为 G5 核心 |

## 3. Release Seed 判断

Release Seed 保留原表、CLI、API 和 Gate。可复用的是 lease/checkpoint/稳定错误码的工程经验，不直接复用其 question-only package、`approved` 终态流程或本地目录读取合同。

长期方向是 `legacy Release Seed package -> adapter -> Canonical Import Core`。本轮不改 legacy package，不让历史 Gate 依赖 G5，也不把 G5 的 module/handout 字段塞入 Release Seed V1。

## 4. 四条生产链现状

四条受保护链已有 registry、manifest、portable dry-run、artifact/job schema 和执行 fail-closed 基础，但不存在共同的生产结果 emission。G5 只定义它们未来共同提交的 Java 合同，不修改链内 prompt、节点、模型、route 或输出算法。

链适配器未来必须在受控边界将各自结果映射为 `teachbase.canonical-content-import.v1`，再调用 G5 API；G5 不读取开发机历史 outputs，也不扫描用户目录。

## 5. 身份与幂等边界

四类概念永久分离：

```text
stable identity != immutable revision != occurrence != source evidence
```

- Package：workspace + packageKey 稳定；相同 hash replay，不同 hash conflict。
- Asset：Question 使用现有 external/source identity，Module 使用 moduleKey，Editor 使用 importDocumentKey。
- Revision：同稳定资产 + content hash 复用，不同内容追加。
- Evidence：revision 内 evidenceKey 幂等；同 key 不同 payload fail closed。
- Occurrence：editor document 内 occurrenceKey 稳定；同 frozen editor revision 不允许第二份不同 composition。

调用方不能提供数据库 UUID 作为业务身份逃生口。包内使用逻辑 key，执行器通过已完成 operation 的 target map 解析数据库 ID。

## 6. 两阶段与 DAG

Validate 会持久化 canonical package JSON、hash 和完整 operation plan，但不创建业务 revision。Commit/Resume 按拓扑顺序执行：

```text
file reference
  -> source document -> source region
  -> question revision -> question provenance -> taxonomy/review intent
  -> module revision -> module provenance/file/taxonomy/review intent
  -> editor revision -> teacher composition -> student projection/artifacts
```

数组顺序只决定同类型稳定展示顺序，不决定依赖发现。每个 operation 显式保存 dependency keys。

## 7. 事务与恢复

一个 operation 是一个短事务：领域写入和 ledger completion 同事务提交。失败由外层在独立事务写入结构化错误。已完成 operation 不删除；resume 先核对 package hash和 completed target，再从 failed/pending dependency frontier 继续。

并发由 request lease 和数据库行锁仲裁。同 package 四路提交只能有一个执行者，其余返回 busy 或最终 replay。失效 lease 可回收。

## 8. G4 语义锁定

### ordinary_content

仅用于无需独立 identity/revision/Review/reuse/search/lifecycle 的讲义局部内容。Question、标准模块、Knowledge Document 或任何开始需要独立生命周期的对象不得塞入 localContent。

### frozen composition

一个精确 editor revision 最多一份 canonical composition。相同 payload replay；不同 payload fail closed。内容变化必须产生 editor revision N+1，再为 N+1 创建 composition。G5 不创建 composition v2/v3，也不覆盖 V009 行。

## 9. 风险与控制

1. 超长事务：按 operation 拆分，composition 自身保持单事务。
2. ledger 与资产漂移：completion 与领域写入同事务；resume 校验 target 存在和 hash。
3. 调用模块私有实现：新增窄 `::api` gateway，Modulith Gate 验证。
4. student 复制资产：student 只保存 projection/delta，包 validator 禁止 student 自带 question/module 数组。
5. validation 后换包：ledger 保存 canonical package JSON 与 SHA-256，commit 只按 request ID + hash 执行。
6. 故障注入污染生产：仅在显式测试开关下启用，默认 fail closed。
7. 主标签规则未决：`BLOCKS_TAG_SCHEMA_AND_SEARCH` 保持 OPEN；G5 只接受现有合法 relationType，不做替换决策。

## 10. 实施边界

V010 只追加 import ledger、operation ledger、必要索引和 editor import identity。不会重写 V009 composition、question/module、WP-01 revision/snapshot，也不会删除 Release Seed 表。

本轮不实现 Risk 自动放行、S02 路由、搜索、推荐、AI、Knowledge Document、Question Group、OIDC、renderer 新能力、四链内部改造或生产数据灌入。
