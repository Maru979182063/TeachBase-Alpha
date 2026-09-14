# TeachBase 教师标签纠偏反馈闭环只读审计

审计日期：2026-09-14

审计分支：`backend/g5-canonical-content-import-recovery`

审计 HEAD：`30c59351cd60a9f668639344e38cdb82fb612f02`
审计性质：只读设计审计；除本报告外未修改 migration、Java、G5、taxonomy 数据、前端、prompt 或模型。

状态标记：

- `IMPLEMENTED`：存在 schema、应用服务/API 和当前 HEAD 运行证据。
- `STORAGE_ONLY`：底层字段或 JSON 可以容纳信息，但没有稳定领域合同或完整运行路径。
- `DOCUMENTED_ONLY`：文档提出过，但当前代码没有实现。
- `PARTIAL`：仅覆盖业务闭环的一部分。
- `MISSING`：当前不存在正式表达和运行路径。
- `NOT_RECOMMENDED`：技术上可以绕用，但领域语义会冲突。

## 1. Executive Summary

当前后端不能完整支撑“系统原判 -> 教师终判 -> 修改原因 -> 当前有效标签 -> 历史反馈 -> taxonomy gap 治理”闭环，但已有底座足够，不需要推翻 G5、Question Governance 或 taxonomy。

现有能力可以稳定表达：

- 稳定 `question` 与精确、内容不可变的 `question_revision`；
- 版本化、激活后不可变的 taxonomy；
- 指向精确 question revision 和 taxonomy version/node 的单条主/副标签关系；
- 题目内容 Review、append-only decision evidence 和 approved pointer；
- G5 package、初始 taxonomy assignment、来源证据、actor/workspace 和完整 package JSON；
- G5 package 级幂等、Review case 级并发串行化、WP-01 autosave 的 CAS/idempotency 实现范式。

关键缺口是“标签集合”没有领域身份：当前只有一条条 `question_taxonomy_link`，没有模型运行、完整原判集合、完整人工终判集合、before/after feedback、current pointer、taxonomy gap、标签状态版本或 mutation idempotency。当前 `question_revision.primary_knowledge_tag` 与 normalized taxonomy link 还可能表达不同值；搜索实际读取前者，不读取后者。

本审计唯一推荐：

```text
tagging_run
  -> immutable SYSTEM_SUGGESTION snapshot
  -> immutable HUMAN_FINAL snapshot
  -> immutable feedback(before_snapshot, after_snapshot)
  -> question_tag_state.current_snapshot_id  [唯一当前业务权威]
  -> question_taxonomy_link                  [同事务兼容投影]
```

历史与训练统计读取 snapshot、feedback、tagging run；在线业务读取 `question_tag_state.current_snapshot_id`；`question_taxonomy_link` 仅为已有消费者提供当前集合的 normalized projection。`question_revision` 内旧自由文本标签保留为导入时内容快照，不再作为教师终判 authority。

最终建议：`GO`。可以启动一个边界严格的后续工作包实施标签反馈基础；不存在必须先由产品负责人决定的阻塞项。是否让 `taxonomy_gap` 阻断题目发布是后续发布策略，本工作包可以只记录并暴露 `tagStatus`，不改变现有 Question Review/approved pointer。

## 2. Current Backend Capabilities

### 2.1 Question 与 revision

| 能力 | 状态 | 代码证据 | 结论 |
|---|---|---|---|
| 稳定题目 identity | `IMPLEMENTED` | `V004__question_search_and_collection_snapshots.sql:7-35` | `question_id` 与 workspace/source/external key 唯一性已存在。 |
| 精确 question revision | `IMPLEMENTED` | `V004...sql:39-88` | revision number、content hash、review status 和 provenance 均落库。 |
| 应用路径内容不可变 | `IMPLEMENTED` | `JooqQuestionRepository.java:61-150,309-346` | 内容只在 import 时 INSERT；Review 只更新 `review_status/approved_at`。数据库目前没有覆盖所有内容列的通用 immutable trigger，因此结论限定为正式应用路径。 |
| 标签不单独产生 revision | `PARTIAL` | `question_taxonomy_link` 独立于 `question_revision`；但 `QuestionService.java:143-165` 又把自由文本主副标签计入 semantic content hash | normalized taxonomy link 支持独立修改方向；旧自由文本字段仍形成兼容债务。 |
| 来源/provenance | `IMPLEMENTED` | `V009__handout_content_asset_and_composition.sql:13-49`、`JooqQuestionRepository.java:350-379` | 一 revision 可有多条 keyed source evidence，冲突 fail closed。 |

### 2.2 Taxonomy

| 能力 | 状态 | 代码证据 | 结论 |
|---|---|---|---|
| taxonomy version/node/alias | `IMPLEMENTED` | `V005__question_governance_foundation.sql:116-188` | 稳定 key、显式 version、树节点和 alias 已具备。 |
| 一个 active version | `IMPLEMENTED` | `V005...sql:144-149` | 每 workspace/taxonomy key 仅一个 active version。 |
| active version 不可修改 | `IMPLEMENTED` | `JooqTaxonomyRepository.java:77-151`；live gate `tools/run_question_governance_live_gate.mjs:236-246` | 节点只能在 draft version 创建。 |
| code/alias 精确解析 | `IMPLEMENTED` | `TaxonomyController.java:49-57`、`JooqTaxonomyRepository.java:154-180` | 可用于 G5 和提交校验。 |
| 节点浏览/模糊选择 API | `MISSING` | `TaxonomyController.java:29-69` | 只有创建、激活、resolve、assign；教师标签选择器没有分页搜索/children 查询接口。 |
| 单条 question assignment | `IMPLEMENTED` | `TaxonomyController.java:59-63`、`TaxonomyService.java:93-116` | 能追加一条主/副关系，绑定精确 revision。 |
| 完整 assignment set | `MISSING` | `TaxonomyCatalog.java:10-23` | 没有读取、替换或确认完整标签集合的合同。 |

### 2.3 Review

| 能力 | 状态 | 代码证据 | 结论 |
|---|---|---|---|
| 内容 Review case | `IMPLEMENTED` | `V005...sql:54-86`、`ReviewController.java:28-44` | 每 question revision 最多一个 open case。 |
| append-only terminal decision | `IMPLEMENTED` | `V005...sql:88-114`、`JooqReviewRepository.java:90-138` | 一个 case 只允许一个批准/拒绝决定。 |
| 内容 hash 并发保护 | `IMPLEMENTED` | `ReviewService.java`、`JooqReviewRepository.java:90-131` | row lock 与 expected hash 阻止并发双决策。 |
| 标签纠偏 feedback | `NOT_RECOMMENDED` | `DecideReviewCaseRequest.java:15-24`、`JooqQuestionRepository.java:309-346` | decision 只能 approved/rejected，且会改变题目 Review 状态与 approved pointer；不适合可多次发生的标签纠偏。 |
| `evidence_json` 容纳标签数据 | `STORAGE_ONLY` | `V005...sql:99-113` | JSON 可塞入 before/after，但不可约束主标签唯一、不可形成 current state，也不适合统计和独立生命周期。 |

### 2.4 Actor、workspace 与 audit

| 能力 | 状态 | 代码证据 | 结论 |
|---|---|---|---|
| workspace 复合外键隔离 | `IMPLEMENTED` | `V001__foundation.sql:1-40` 及后续业务表复合 FK | 数据层可阻止跨 workspace 引用。 |
| active member 校验 | `IMPLEMENTED` | `JooqWorkspaceDirectory.java:25-42` | taxonomy/review 现有服务验证 active workspace member。 |
| 成员角色和教学范围 | `PARTIAL` | `V001...sql:31-40`、`V007__member_teaching_scope.sql:1-28` | 数据结构已存在；`TaxonomyService.java:161-164` 当前 assignment 只校验 active member，没有 reviewer/editor 角色和 subject/stage scope 校验。 |
| append-only audit event | `IMPLEMENTED` | `V001...sql:140-156`、`JooqAuditTrail.java:31-42` | 可记录命令事件，但 audit log 不能替代标签领域事实。 |

## 3. Current Gaps

按审计问题逐项定级：

| # | 审计问题 | 状态 | 当前事实 |
|---|---|---|---|
| 1 | 一次模型打标运行 | `MISSING` | 无 `tagging_run` 或等价领域对象。G5 package JSON 可保存任意 metadata，但不是模型运行合同。 |
| 2 | 不可变系统原判完整集合 | `PARTIAL` | G5 package 整体被冻结；单条 taxonomy link 可追加。但没有“集合”identity/hash/run，link 也没有数据库 immutable 保护。 |
| 3 | 不可变人工最终完整集合 | `MISSING` | 可追加 `assignmentSource=human`，但不能声明它是一套完整终判，也没有历史 set、current pointer 或主标签唯一性。 |
| 4 | 标签 Feedback | `MISSING` | Review 是内容批准/拒绝，语义不适用。 |
| 5 | 当前有效标签 | `MISSING` | 无 current pointer；搜索读取 revision 自由文本，taxonomy link 是另一份可能冲突的数据。 |
| 6 | `question_taxonomy_link` 定位 | `PARTIAL` | 当前是 additive assignment store；推荐迁移为新 authority 的兼容/current projection。 |
| 7 | 每维度最多一个 primary | `MISSING` | 唯一约束是 `(question_revision_id, taxonomy_node_id, relation_type)`，允许不同 node 都为 primary。 |
| 8 | 前后状态差异 | `MISSING` | 无 before/after set；无法可靠自动推导。 |
| 9 | Taxonomy Gap | `MISSING` | 无 case、状态、resolution node 或 triage lifecycle。 |
| 10 | 标签并发 CAS | `MISSING` | Review/WP-01 有可借鉴模式；taxonomy assignment 本身没有 state version。 |
| 11 | 标签提交幂等 | `MISSING` | G5 package 和 editor autosave 幂等作用域不同，不能复用其 ledger。 |
| 12 | 只改标签不建 question revision | `PARTIAL` | normalized link 的表边界支持；旧自由文本标签仍参与 question content hash，需要明确降级为 legacy snapshot。 |

## 4. Existing Table/API Reuse Matrix

| 现有对象 | 复用方式 | 不得承担的职责 |
|---|---|---|
| `question` | 稳定题目 identity | 不保存每次标签反馈。 |
| `question_revision` | 标签 snapshot/feedback 必须绑定的精确内容版本 | 不因只改标签而创建 revision；不把 current tag pointer 塞进不可变内容。 |
| `question_revision.primary_knowledge_tag` / `secondary_knowledge_tags_json` | 旧导入内容快照和兼容 fallback | 不再作为教师终判 authority。 |
| `taxonomy_version` / `taxonomy_node` | 精确知识树版本和最终 node FK | 不保存模型运行或反馈正文。 |
| `question_taxonomy_link` | 当前标签的 normalized 兼容投影；迁移期间也可作为 legacy baseline 输入 | 不作为历史原判、feedback 或唯一 authority。 |
| `review_case` / `review_decision` | 继续负责题目内容批准/拒绝；复用其锁、409 和 audit 设计经验 | 不直接承载标签纠偏。 |
| `question_import_observation` | 保留不同 import envelope/provenance 的到达事实 | 不等价于模型标签运行或教师反馈。 |
| `canonical_import_request.package_json` | 关联原始 G5 package、lineage 和 producer metadata | 不作为可查询 tagging run 主表。 |
| `source_document` / `source_region` / `question_source_link` | 为反馈页面展示题源，辅助教师判断 | 不表达模型/教师标签版本。 |
| `workspace_member` / teaching scope | actor、workspace、角色和学科/学段范围校验 | 不在标签表重复用户资料。 |
| `audit_event` | 记录 submit/replay/conflict/gap transition 等事件 | 不作为 current state 或训练事实源。 |
| WP-01 mutation pattern | 借鉴 `expectedVersion + clientMutationId + payload hash` | 不复用 `editor_autosave_mutation` 表。 |
| G5 import ledger pattern | 借鉴 package key/hash 冲突 fail closed | 不复用 `canonical_import_request` 充当教师 mutation ledger。 |

## 5. Recommended MVP Domain Model

推荐保留候选模型中的六个逻辑对象，不再增加“operation type history”之类的独立表：

```text
tagging_run
  1 ─── n question_tag_snapshot(kind=SYSTEM_SUGGESTION)

question_revision
  1 ─── n question_tag_snapshot
            1 ─── n question_tag_snapshot_item

question_tag_feedback
  before_snapshot_id ──> question_tag_snapshot
  after_snapshot_id  ──> question_tag_snapshot (HUMAN_FINAL，可在 gap 时为空/部分)

question_tag_state
  current_snapshot_id ──> question_tag_snapshot
  current_feedback_id ──> question_tag_feedback

taxonomy_gap_case
  feedback_id ──> question_tag_feedback
  resolved_node_id ──> taxonomy_node（可为空）
```

### 5.1 `tagging_run`

必要。它表示一次模型分类运行，而不是一次 G5 import。

最小字段：

- `tagging_run_id`、`workspace_id`、稳定 external run key；
- `taxonomy_version_id`；
- model provider/name/version；
- prompt/profile version；
- candidate package key/version/hash；
- producer/runtime version；
- run parameters JSON + parameters hash；
- status、started_at、completed_at；
- 可选 `canonical_import_request_id`；
- created/registered actor 与时间。

同一 run 可覆盖多道题，也可以在 G5 之外重新执行，因此不能与 canonical import request 一一等同。

### 5.2 `question_tag_snapshot`

必要。每行是精确 question revision、精确 taxonomy version 下的一套完整标签事实。

建议字段：snapshot kind、content hash、question/revision、taxonomy version、可选 tagging run、created actor/time。允许 kind 至少为：

- `system_suggestion`
- `human_final`
- `import_baseline`
- `inherited_candidate`

snapshot 创建后禁止 UPDATE/DELETE。相同 `(question_revision, taxonomy_version, kind, content_hash, tagging_run)` 可幂等复用。

### 5.3 `question_tag_snapshot_item`

必要。用关系行保存 node、`primary/secondary`、position、confidence、candidate rank。相比只存 JSON，它能提供 FK、主标签唯一约束和高质量统计。

关键约束：

```sql
unique (snapshot_id, taxonomy_node_id)
unique (snapshot_id) where relation_type = 'primary'
```

snapshot 自身只绑定一个 taxonomy version，因此部分唯一索引等价于“该集合该 taxonomy dimension 最多一个 primary”。

### 5.4 `question_tag_feedback`

必要。保存 before/after snapshot、outcome、可选 reason/note、reviewer、submitted_at、`client_mutation_id`、request hash、`expected_state_version`。

`operationTypes` 可以在提交时自动计算并作为缓存 JSON/array 保存，方便查询；但它不是唯一历史事实。before/after snapshots 才是事实，operation types 必须可以重新推导。

### 5.5 `question_tag_state`

必要。它是唯一 current authority 和并发边界。

建议唯一键：

```text
(workspace_id, question_revision_id, taxonomy_key)
```

最小字段：current taxonomy version、current snapshot、current feedback、`state_version`、status、updated actor/time。status 至少包括：

- `pending`
- `reviewed`
- `taxonomy_gap`
- `needs_reconciliation`（历史多 primary 等无法自动 backfill 的情况）

### 5.6 `taxonomy_gap_case`

必要，但保持最小。若只把 `gap=true` 塞进 feedback，无法表达后续 triage、映射到新版本节点和关闭过程。

最小字段：question revision、feedback、报告时 taxonomy version、expected label text、teacher explanation、status、resolved taxonomy version/node、created/resolved actor/time。状态变化历史复用 `audit_event`，MVP 不再新增 gap event 表。

## 6. Tables That Are Actually Necessary

| 候选表 | 判断 | 是否可合并/复用 | 理由 |
|---|---|---|---|
| `tagging_run` | 必须新增 | 不应复用 G5 import request | 模型运行与导入运行不是同一生命周期；一 run 可跨多个 package/question。 |
| `question_tag_snapshot` | 必须新增 | 不应复用 question revision | 标签变化不应制造题目内容 revision。 |
| `question_tag_snapshot_item` | 必须新增 | 不建议只存 snapshot JSON | 需要 node FK、primary 唯一和可查询统计。 |
| `question_tag_feedback` | 必须新增 | 不应复用 Review decision | 标签反馈可多次发生，且不能改变内容审核状态。 |
| `question_tag_state` | 必须新增 | 不能只靠 max(created_at) | 需要明确 authority、CAS 和 O(1) 当前读取。 |
| `taxonomy_gap_case` | MVP 必须新增 | triage 历史复用 audit event | gap 与模型选错必须分流，且具有独立治理生命周期。 |

结论：候选的五个命名块实际对应六张表（snapshot + item）。这不是为了概念完整而扩表；每张表分别关闭 run、集合 FK、反馈、current concurrency、gap lifecycle 五类不同约束，无法安全压成现有表或一个 JSON blob。

## 7. Authority / Source-of-Truth Decision

唯一推荐如下，不保留备选双真相：

```text
历史事实：question_tag_snapshot + snapshot_item + feedback + tagging_run
当前权威：question_tag_state.current_snapshot_id
兼容投影：question_taxonomy_link
旧文本字段：question_revision.primary_knowledge_tag / secondary_knowledge_tags_json
          仅为 legacy imported-content snapshot
```

### 7.1 教师提交事务

一个数据库事务内执行：

1. 校验 workspace、actor 角色/教学范围、question revision、taxonomy version 和所有 node FK；
2. 按 `clientMutationId` 查重并校验 request hash；
3. 校验 before snapshot 是当前可见建议/状态；
4. 建立或复用完整 HUMAN_FINAL snapshot + items；
5. 自动计算 diff，建立 feedback；
6. gap 时建立 `taxonomy_gap_case`；
7. CAS 更新 `question_tag_state`：`WHERE state_version = expectedStateVersion`；
8. 用新 snapshot 的 items 替换精确 `(question_revision_id, taxonomy_version_id)` 的 `question_taxonomy_link` current projection；
9. 写 audit event；
10. commit。

### 7.2 投影失败

`question_taxonomy_link` 与 state/snapshot 在同一个 PostgreSQL 事务内更新。任何 constraint、FK 或写入失败都回滚 snapshot、feedback、state 和 projection，不能异步“稍后修”，因此不会出现 state=B、link=A 的已提交状态。

### 7.3 消费者迁移

1. 新标签审核 API 只读 `question_tag_state -> snapshot items`。
2. 旧消费者短期继续读 `question_taxonomy_link` current projection。
3. `QuestionSearchItem` 当前读取 `question_revision.primary_knowledge_tag`（`JooqQuestionRepository.java:226-267`），后续工作包必须做一个窄改动，改读 current projection/state；否则老师改签后搜索展示仍是旧文本。
4. 所有消费者迁移后，`question_taxonomy_link` 仍可保留为高效 normalized read projection，不再承担历史。

### 7.4 统计与训练

训练/评估导出必须从 `tagging_run + SYSTEM_SUGGESTION snapshot + HUMAN_FINAL snapshot + feedback + gap` 读取。不得从 current projection 反推历史，因为 projection 只保留当前值。

## 8. Snapshot and State Semantics

推荐的 snapshot 模式适合 TeachBase，原因是它与现有 immutable revision、snapshot/export 和 G5 package freezing 一致。

规则：

- snapshot 是完整集合，不是 patch；
- snapshot 精确绑定 question revision 和 taxonomy version；
- snapshot item 最多一个 primary，可有多个 secondary；
- model confidence/candidate rank 只对 system suggestion 有意义，human final 可为空；
- old snapshot 永不改写；
- feedback 连接 before/after，并保存人工 reason/note；
- state pointer 决定当前集合，不使用 `max(created_at)` 猜测；
- taxonomy gap 可以让 state 进入 `taxonomy_gap`，此时不允许把旧系统建议伪装成“老师已确认”；
- 新 question revision 可以建立 `inherited_candidate`，但不能自动建立 `human_final`。

若 gap 时老师仍选出部分 secondary，可保存一个没有 primary 的 HUMAN_FINAL snapshot；`state.status=taxonomy_gap` 明确表示它不可被当作完整 tag-ready 集合。

## 9. Primary Uniqueness Strategy

当前数据库仍允许同一 question revision + taxonomy version 存在多个 primary：

```text
uq_question_taxonomy_link
  = (question_revision_id, taxonomy_node_id, relation_type)
```

证据：`V005__question_governance_foundation.sql:190-217`。不同 node ID 不冲突，因此 A-primary 与 B-primary 可以同时插入。

MVP 处理策略：

1. 新 snapshot item 层立即用部分唯一索引保证每 snapshot 最多一个 primary；
2. normal `human_final` 要求恰好一个 primary；gap/needs_reconciliation 允许零个；
3. 不在本工作包自动清理旧 link；
4. backfill 遇到多个 legacy primary 时创建 `import_baseline` 并把 state 标记为 `needs_reconciliation`，不猜谁是正确主签；
5. 老师提交完整新集合后，current projection 由新 snapshot 重建；旧历史 snapshot 永久保留。

因此“旧主标签降级还是删除”不再阻塞数据模型：历史事实不变，current pointer 切换到新集合。UI 是否把某个旧主标签自动放入 secondary 是交互建议，不是持久化历史规则；最终以老师提交的完整集合为准。

## 10. Taxonomy Gap Strategy

当前 schema 没有正式 taxonomy gap。自由文本 note、Review evidence 或 audit payload 都只能临时容纳，不能提供治理队列。

MVP `taxonomy_gap_case` 应支持：

- 精确 question revision；
- 报告时 taxonomy version；
- before/system suggestion snapshot；
- teacher expected label text；
- teacher explanation；
- `open/triaged/resolved/rejected`；
- 可选 resolved taxonomy version/node 或 mapping note；
- reporter、assignee、created/resolved time；
- audit_event 记录 triage/resolve/reopen。

统计口径必须把 `taxonomy_gap` 从“model wrong”准确率分母/分子中单独列出，避免用知识树缺口错误惩罚模型。

MVP 不自动创建 taxonomy node，不自动修改 active taxonomy version。解决 gap 仍通过现有 draft -> active taxonomy version 流程。

## 11. Optimistic Locking & Idempotency

### 11.1 并发

当前标签 assignment 没有 CAS。两个老师都基于 state version 7 时，最小正确实现是：

```sql
update question_tag_state
set current_snapshot_id = :after,
    current_feedback_id = :feedback,
    state_version = state_version + 1,
    updated_by = :actor,
    updated_at = now()
where workspace_id = :workspace
  and question_revision_id = :revision
  and taxonomy_key = :taxonomyKey
  and state_version = :expectedVersion;
```

受影响行数不是 1 时，整个事务回滚并返回 409，响应携带最新 `stateVersion/currentSnapshot`。失败请求不能留下 orphan snapshot/feedback。

首次创建 state 的并发由唯一键 `(workspace_id, question_revision_id, taxonomy_key)` 兜底；服务可先 `INSERT ... ON CONFLICT DO NOTHING` 再进入 CAS。

可直接借鉴而不能直接复用：

- Review 的 `SELECT ... FOR UPDATE` + 409：`JooqReviewRepository.java:90-131`；
- WP-01 `expectedDraftVersion + clientMutationId`：`V008__editor_working_draft_separation.sql:9-63`。

### 11.2 幂等

标签 mutation 使用客户端生成的 UUID 字符串 `clientMutationId`。推荐唯一作用域：

```text
(workspace_id, client_mutation_id)
```

feedback 保存 canonical request hash：

- 同 mutation ID、同 request hash：返回首次成功的 feedback/state，`replayed=true`，不增加 state version；
- 同 mutation ID、不同 request hash：409 `tag_feedback_idempotency_payload_conflict`；
- 不创建第二个 HUMAN_FINAL snapshot、feedback 或 gap case。

feedback 是永久审计数据，因此 mutation identity 可与 feedback 一起长期保留，不需要像 autosave mutation 那样 7 天清理。

G5 `packageKey + packageHash` 幂等（`V010...sql:16-73`）和 editor autosave 幂等都是局部领域能力，没有一张可安全复用的通用 idempotency 表。

## 12. G5 Integration Boundary

建议关系成立：

```text
生产解析链
  -> 模型标签
  -> G5 Canonical Import
  -> Question Revision + initial question_taxonomy_link
  -> register tagging_run
  -> SYSTEM_SUGGESTION snapshot
  -> Teacher Correction
  -> HUMAN_FINAL snapshot + Feedback + Tag State
```

当前 G5 能力：

- `taxonomyAssignments` 已携带 target、精确 taxonomy version、node code/alias、primary/secondary、human/model/import source；见 `canonical_content_import_v1.schema.json:120-131`。
- executor 可读取可选 confidence 并调用 taxonomy port；见 `CanonicalImportOperationExecutor.java:181-197`。
- 顶层 `lineage` 和 `producerMetadata` 是开放 object；见 schema `31-32`。
- V010 `canonical_import_request.package_json` 完整冻结 package，identity trigger 禁止改写；见 `V010...sql:16-67,135-156`。

不足：

- `producerMetadata` 没有 model/modelVersion/promptVersion/candidatePackage/run timestamps 的 required schema；
- metadata 只在 package JSON 中整体保存，缺少 normalized index/API；
- G5 import request 表示收货执行，不等价于模型运行；
- 当前 G5 不会创建 SYSTEM_SUGGESTION snapshot。

推荐非破坏集成：保持 Canonical Import v1 不变。G5 成功后，由 producer/intake adapter 或后续 Java orchestration 调用独立 tagging-run/suggestion API，携带 `canonicalImportRequestId`、run context 和初始完整标签集合。已冻结 package 可作为原始证据和 hash 锚点。

结论：

`G5_NO_BREAKING_CHANGE_REQUIRED`

## 13. Minimal API Proposal

本节从教师操作反推合同，不代表已实现。

### 13.1 获取审核上下文

```http
GET /api/v1/question-revisions/{questionRevisionId}/tag-review-context?taxonomyKey=...
```

建议响应：

```json
{
  "questionRevisionId": "uuid",
  "taxonomyKey": "high-school-math",
  "taxonomyVersionId": "uuid",
  "stateVersion": 7,
  "tagStatus": "pending",
  "systemSuggestion": {
    "snapshotId": "uuid",
    "taggingRunId": "uuid",
    "primary": {"taxonomyNodeId": "uuid", "code": "A", "name": "A", "confidence": 0.82},
    "secondary": [
      {"taxonomyNodeId": "uuid", "code": "B", "name": "B", "confidence": 0.65},
      {"taxonomyNodeId": "uuid", "code": "C", "name": "C", "confidence": 0.53}
    ]
  },
  "current": null,
  "runContext": {
    "model": "...",
    "modelVersion": "...",
    "promptProfileVersion": "...",
    "candidatePackageVersion": "...",
    "candidatePackageHash": "sha256"
  }
}
```

### 13.2 节点选择

现有 resolve 只支持精确 code/alias。标签表单至少需要一个窄 taxonomy 查询接口，不等价于统一资产搜索：

```http
GET /api/v1/taxonomy-versions/{taxonomyVersionId}/nodes?query=圆&parentNodeId=&cursor=&limit=30
```

只返回当前显式 version 内的 node ID、code、name、parent/path；不启动 unified search。

### 13.3 提交教师终判

```http
POST /api/v1/question-revisions/{questionRevisionId}/tag-feedback
```

正常修改 request：

```json
{
  "workspaceId": "uuid",
  "actorUserId": "uuid",
  "taxonomyKey": "high-school-math",
  "taxonomyVersionId": "uuid",
  "beforeSnapshotId": "uuid",
  "expectedStateVersion": 7,
  "clientMutationId": "uuid",
  "finalPrimaryNodeId": "uuid-B",
  "finalSecondaryNodeIds": ["uuid-C", "uuid-D"],
  "reasonCodes": ["LABEL_GRANULARITY_UNSUITABLE"],
  "note": ""
}
```

taxonomy gap request：

```json
{
  "workspaceId": "uuid",
  "actorUserId": "uuid",
  "taxonomyKey": "high-school-math",
  "taxonomyVersionId": "uuid",
  "beforeSnapshotId": "uuid",
  "expectedStateVersion": 7,
  "clientMutationId": "uuid",
  "taxonomyGap": {
    "expectedLabelText": "...",
    "explanation": "现有树中没有对应粒度节点"
  },
  "finalSecondaryNodeIds": [],
  "reasonCodes": [],
  "note": ""
}
```

建议响应：

```json
{
  "feedbackId": "uuid",
  "replayed": false,
  "stateVersion": 8,
  "tagStatus": "reviewed",
  "currentSnapshotId": "uuid",
  "derivedOperations": [
    "PRIMARY_SECONDARY_SWAP",
    "SECONDARY_REMOVED",
    "SECONDARY_ADDED"
  ],
  "taxonomyGapCaseId": null
}
```

409 必须返回 machine-readable problem code、最新 state version 与最新 current snapshot summary，供前端做刷新/人工合并。

### 13.4 历史、治理与导出

MVP 还需要只读分页合同：

- `GET /api/v1/question-revisions/{id}/tag-feedback-history`
- `GET /api/v1/tag-feedback?taggingRunId=&taxonomyVersionId=&outcome=&reasonCode=&cursor=`
- `GET /api/v1/taxonomy-gaps?status=&taxonomyVersionId=&cursor=`
- `GET /api/v1/tag-feedback/export?...`，输出 versioned JSONL/JSON package，固定 snapshot/run/node IDs 与 hashes。

## 14. Migration Impact Estimate

预计为中等、纯追加 migration 候选，建议下一版本使用新的 Flyway migration，不修改 V001-V010 历史文件。

范围：

- 6 张新表；
- snapshot item 的 partial unique primary index；
- state lookup/CAS index；
- feedback mutation unique index；
- run/version/time 与 gap queue 索引；
- snapshot/run/feedback 的 immutable update/delete fence；
- 对 question/taxonomy/workspace/member/canonical import 的复合 FK；
- jOOQ regenerate；
- taxonomy 查询、tagging、feedback repository/service/API；
- question search current-tag 兼容读取。

不需要：

- 重写 question、question revision、Review 或 G5；
- 修改历史 revision/hash；
- 批量删除旧 taxonomy link；
- 更新四条生产链内部逻辑；
- 修改 prompt/model。

### Backfill

- 初期优先 lazy backfill：某 question revision 首次进入标签审核时，从现有 `question_taxonomy_link` 构造 `import_baseline/system_suggestion`。
- 如果 package 可关联 G5 request 和 producer metadata，再关联/登记 tagging run。
- 只有 revision 自由文本、没有 node FK 时，保留文本 evidence 并标记 `needs_reconciliation`，不进行模糊自动映射。
- 多个 legacy primary 一律 `needs_reconciliation`，不自动删除或降级。
- backfill 通过唯一 hash/key 可重入；与教师提交并发时由 state unique key + CAS 决胜。

## 15. Existing Consumer Compatibility

### 当前真实消费者

- G5 与 Release Seed 调用 `TaxonomyCatalog.assign` 追加 link。
- taxonomy API 返回单条 link ID，不返回完整集合。
- question search 读取 `question_revision.primary_knowledge_tag`，不 join normalized links。
- editor/collection 固定 question revision，不会因标签修正改变内容引用。
- Review 决定更新 question revision review status 和 question approved pointer。

### 兼容计划

1. 保持 `TaxonomyCatalog.assign`，供 G5/legacy importer 写入初始 projection；同时在成功 import 后登记 system suggestion。
2. 新教师 API 只写新 authority，并在同事务重建现有 link projection。
3. 现有 editor、collection、snapshot/export 不需要改引用，因为标签变化不创建 question revision。
4. question search 做窄兼容改造，显示 current primary；没有 state 时 fallback 到 existing link，再 fallback 到 revision text。
5. fallback 必须有指标，确认历史数据完成迁移后才能移除，不能长期静默形成三层猜测。
6. 不把 new state 反写进历史 `question_revision`，避免 content hash 和旧 snapshot 漂移。

## 16. MVP vs Deferred

### MVP 必须支持

| 能力 | 判断 |
|---|---|
| model/system original suggestion | 必须；immutable snapshot。 |
| human final snapshot | 必须；完整集合。 |
| current state | 必须；唯一 pointer + version。 |
| before/after feedback | 必须；绑定精确 snapshots。 |
| 自动 diff | 必须；服务端确定性推导。 |
| reason/note | 必须支持但可选；gap explanation 除外。 |
| taxonomy gap | 必须；独立 case/lifecycle。 |
| actor/time | 必须；复用 workspace member/audit。 |
| model/prompt/taxonomy/candidate context | 必须；normalized tagging run + hashes。 |
| optimistic locking | 必须；CAS + 409。 |
| idempotent mutation | 必须；client mutation + request hash。 |
| query/export | 必须；分页查询和版本化 JSON 导出即可。 |
| taxonomy node picker query | 必须；只做版本内节点搜索/浏览。 |
| reviewer authorization | 必须；复用角色与教学范围，不能只校验 active member。 |

### 延后

- 自动更新 prompt；
- 自动训练和在线学习；
- 自动修改 taxonomy 或创建 node；
- feedback 自动质量裁决；
- 大型 analytics dashboard；
- recommendation；
- unified asset search；
- 教师评分；
- 自动决定 gap 是否阻断题目发布；
- 跨 taxonomy version 自动映射标签。

## 17. Risks

1. **现有双真相**：revision 自由文本与 normalized link 已可能不一致；若新增 state 后不明确 authority，会变成三份真相。
2. **投影事务边界**：state 与 `question_taxonomy_link` 分事务更新会产生短暂或永久 split brain，必须同事务。
3. **搜索陈旧**：当前 search 返回 revision free-text primary；不做窄兼容改造，老师会以为修改未生效。
4. **历史脏数据**：旧 link 可能多 primary；backfill 不能猜测，必须进入 reconciliation。
5. **把 gap 算成模型错**：会污染准确率、prompt 调优和训练数据。
6. **Review 误复用**：会错误改变 approved pointer，甚至让标签修改影响题目可用性。
7. **metadata 黑盒化**：长期只把 run context 放 JSON，会造成版本统计慢、字段漂移、无法约束必填。
8. **权限过宽**：现有 taxonomy assignment 只要求 active member；教师终判至少要明确 reviewer/editor/manager 权限并校验学科/学段范围。
9. **新 revision 继承误确认**：继承只能是 candidate；自动标为 human final 会伪造人工证据。
10. **幂等只去重不校验 payload**：相同 mutation ID 携带不同内容必须 409，不能返回第一次结果掩盖客户端错误。

## 18. Recommended Next Work Package

建议工作包名称：

`TAG-FEEDBACK-01 — Teacher Tag Correction & Taxonomy Gap Foundation`

边界：

1. 追加 migration 与 jOOQ generation；
2. 六个最小领域表及 DB constraints/fences；
3. tagging run 与 suggestion registration API；
4. review context、node picker、feedback submit/history/query/export API；
5. snapshot hash、自动 diff、taxonomy gap；
6. state CAS、client mutation idempotency、workspace/role/teaching-scope authorization；
7. `question_taxonomy_link` 同事务 projection；
8. question search current-primary 窄兼容；
9. G5 后置注册适配，不修改 Canonical Import v1；
10. migration、concurrency、idempotency、legacy backfill、G5/WP-01/Review regression gates。

建议 Golden Acceptance 至少覆盖：

- A(primary), B/C(secondary) -> B(primary), C/D(secondary)；
- 自动推导 swap/remove/add；
- 旧 system snapshot 不变；
- 100 次读取/重复 retry 不生成重复反馈；
- 同 mutation 同 payload replay；同 mutation 不同 payload 409；
- 两教师同 expected version 只有一人成功，失败者不留任何行；
- normal final 最多且恰好一个 primary；
- taxonomy gap 不计为 model wrong；
- 多 primary legacy 数据 fail closed 到 reconciliation；
- 改标签不增加 question revision；
- Review status/approved pointer 不变；
- current state 与 link projection 一致；
- search 展示 current primary；
- 新 question revision 继承为 candidate 而非 human confirmed；
- 跨 workspace/越权/跨学科提交失败；
- G5、G4、WP-01、question governance 全量回归不退化。

## 19. Explicit Product Decisions Still Needed

### 不阻塞本工作包

只有一项后续发布策略尚需产品负责人确定：

> `tagStatus=taxonomy_gap` 的题目是否允许进入正式发布、选题和讲义使用，还是必须先解决 gap。

这不阻塞标签反馈基础实施。默认安全边界是：本工作包只记录并暴露 `tagStatus`，不改变现有 Question Review/approved pointer；等发布策略单独冻结后再增加 gate。

以下不再需要产品决策：

- 旧主标签“删除还是降级”：旧 snapshot 永久保留；current pointer 指向老师提交的完整新集合。
- operation type 是否手填：从 before/after 自动推导，老师不承担额外操作。
- reason 是否必填：普通纠偏可选；taxonomy gap 的 expected text/explanation 必填。
- 只改标签是否建 question revision：不建。
- 是否修改 G5 v1：不修改。

因此：`是否存在阻塞产品决策：NO`。

## 20. Final Go / No-Go Recommendation

`GO`

当前 backend foundation 足以承接最小标签反馈工作包；所需变化是纯追加的标签治理子域与少量兼容读取，不需要重构 G5、Question、Review、editor 或四条生产链。

明确结论：

```text
TAG_FEEDBACK_AUDIT_COMPLETE

推荐：
使用 immutable SYSTEM_SUGGESTION/HUMAN_FINAL snapshots 保存事实，
使用 question_tag_state.current_snapshot_id 作为唯一当前业务权威，
使用 question_taxonomy_link 作为同事务 compatibility/current projection。

现有可复用：
question/question_revision、taxonomy version/node、source provenance、
workspace/member/teaching scope、audit、Review/WP-01/G5 的并发和幂等实现范式。

MVP 必须新增：
tagging_run、question_tag_snapshot、question_tag_snapshot_item、
question_tag_feedback、question_tag_state、taxonomy_gap_case，
以及 context/node-query/submit/history/query/export API。

可以延后：
自动 prompt 优化、训练、在线学习、自动 taxonomy 修改、复杂分析看板、
推荐、统一搜索、教师评分和 feedback 自动质量裁决。

是否需要修改 G5：
NO

G5_NO_BREAKING_CHANGE_REQUIRED

是否存在阻塞产品决策：
NO
```

## Appendix A. Current-HEAD Machine Evidence

本轮在 exact HEAD `30c59351cd60a9f668639344e38cdb82fb612f02` 实际执行：

| 命令 | Exit code | 真实结果摘要 | 报告 |
|---|---:|---|---|
| `npm run build:java-foundation` | 0 | Maven clean package、Java tests、Modulith/ArchUnit 构建通过 | Maven console output |
| `npm run test:question-governance-live` | 0 | PostgreSQL live gate passed；2 个并发 Review decision 为 1 success + 1 conflict；1 revision、2 import envelopes、1 revision-pinned taxonomy link | `docs/reports/question_governance_live_gate_20260901.json` |
| `npm run test:g5-workflow-contract` | 0 | `5 passed` | pytest console output |
| `npm run test:g5-import-live` | 0 | PostgreSQL 18.4；24/24 checks；10/10 fault boundaries recovered；4 concurrent callers；circle 320 blocks/31 revisions；English 439 blocks/60 revisions/63 occurrences | `docs/reports/g5_canonical_import_live_gate.json` |

实测报告证明的是既有 Question Governance/G5 能力，不代表标签反馈闭环已经实现。当前没有 tag-feedback migration/API/test，因此相关项目仍按本报告标为 `MISSING`。

## Appendix B. Primary Code Evidence Index

- `backend/teachbase-server/src/main/resources/db/migration/V001__foundation.sql:1-40,140-156`
- `backend/teachbase-server/src/main/resources/db/migration/V004__question_search_and_collection_snapshots.sql:7-114`
- `backend/teachbase-server/src/main/resources/db/migration/V005__question_governance_foundation.sql:29-217`
- `backend/teachbase-server/src/main/resources/db/migration/V007__member_teaching_scope.sql:1-28`
- `backend/teachbase-server/src/main/resources/db/migration/V008__editor_working_draft_separation.sql:9-63`
- `backend/teachbase-server/src/main/resources/db/migration/V009__handout_content_asset_and_composition.sql:13-49`
- `backend/teachbase-server/src/main/resources/db/migration/V010__canonical_content_import_and_recovery.sql:16-201`
- `backend/teachbase-server/src/main/java/com/teachbase/server/question/application/QuestionService.java:61-193`
- `backend/teachbase-server/src/main/java/com/teachbase/server/question/infrastructure/JooqQuestionRepository.java:61-170,175-267,292-379`
- `backend/teachbase-server/src/main/java/com/teachbase/server/taxonomy/application/TaxonomyService.java:93-164`
- `backend/teachbase-server/src/main/java/com/teachbase/server/taxonomy/infrastructure/JooqTaxonomyRepository.java:154-282`
- `backend/teachbase-server/src/main/java/com/teachbase/server/taxonomy/api/TaxonomyController.java:29-69`
- `backend/teachbase-server/src/main/java/com/teachbase/server/review/application/ReviewService.java`
- `backend/teachbase-server/src/main/java/com/teachbase/server/review/infrastructure/JooqReviewRepository.java:34-138`
- `backend/teachbase-server/src/main/java/com/teachbase/server/audit/infrastructure/JooqAuditTrail.java:31-42`
- `backend/teachbase-server/src/main/java/com/teachbase/server/canonicalimport/application/CanonicalImportPlanner.java:55-132,148-196`
- `backend/teachbase-server/src/main/java/com/teachbase/server/canonicalimport/application/CanonicalImportOperationExecutor.java:181-209`
- `config/canonical_import/canonical_content_import_v1.schema.json:1-32,120-140`
- `tools/run_question_governance_live_gate.mjs:124-305`
- `tools/run_g5_canonical_import_live_gate.mjs:243-280,292-327,449-555`
- `tests/test_g5_canonical_import_contract.py:12-75`
