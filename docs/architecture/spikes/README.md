# Phase 0 Isolated Schema Spikes

这三个 spike 只验证表关系、版本固定和并发约束，全部位于 `teachbase_phase0_spike` schema，不属于 Flyway 生产迁移。运行：

```bash
npm run test:phase0-schema-spike
```

测试会启动临时 PostgreSQL、应用现有 V001-V007、应用 spike DDL、写入真实关系样例、执行并发断言，最后删除临时集群。机器报告位于 `docs/reports/phase0_schema_spike_gate_20260902.json`。

## 1. Working Draft Spike

文件：`working_draft_schema_spike.sql`

### 复用关系

- 复用现有 `editor_document` 作为聚合根。
- `based_on_editor_revision_id` 精确引用现有 immutable revision。
- 复用 workspace member 和现有 master-overrides-v1 内容合同。
- snapshot/export 表完全不变。

### 为什么不是重复 editor

spike 只替换“当前可变编辑态”和短期恢复点，不创建第二套 document、variant、revision、snapshot 或 export。正式迁移后仍由现有 editor 模块拥有全部表。

### 迁移与回滚

- 从当前 `editor_draft -> editor_revision` 复制一次内容并建立 `draft_version=1`。
- 双读期间优先新 draft，缺失时懒迁移。
- 回滚应用后继续读旧 pointer；不删除旧 revision/snapshot。
- spike schema 可整体 drop，不影响 `teachbase_app`。

### 真实样例与测试

样例从一个现有 `synchronized_handout` revision 建 working draft。两个并发 `expectedDraftVersion=1` 的 UPDATE 中恰好一个成功，draft version 变为 2；`editor_revision` 数仍为 1；随后创建 72 小时 autosave checkpoint。

### 未解决问题

- 正式清理 worker 的调度时间和每批删除上限。
- 前端冲突合并 UI；后端合同已经确定为 409，不做静默覆盖。

## 2. Knowledge Document + Section Identity Spike

文件：`knowledge_document_schema_spike.sql`

### 复用关系

- 复用 workspace/member、结构化 editor content schema、file/source/question 的精确 revision 引用模式。
- taxonomy 仅通过后续 link 表分类，不承载正文。
- 不复用 `editor_document` 根表，避免引入三变体和讲义导出生命周期。

### 为什么不是重复 editor

只复用内容 schema 和 validator。新增根对象负责 lesson binding；section identity/revision/lineage 是现有 editor 没有的业务事实。讲义仍在 editor 模块，知识文档不生成 teacher/student snapshot。

### Stable identity 与 revision 边界

- `knowledge_section` 根对象只保存稳定 section ID、所属 knowledge document 与身份生命周期，不保存当前标题、位置或正文。
- 每次 `knowledge_document_revision` 下的 `knowledge_section_revision` 保存该版 section 的 parent、order、title、content 和 references。
- 这些字段必须由 `(knowledge_document_revision_id, knowledge_section_id)` 精确寻址，不能通过 stable 根对象上的可变“当前值”读取。
- 新版移动、拆分、合并、改名只追加新版 occurrence 与 lineage；旧 knowledge document revision 的完整 section 树保持原值。
- 当前 spike 表名中的 `knowledge_section_revision` 表达 revision-scoped occurrence，不代表 stable 根对象自身可变。

### 迁移与回滚

- 初期只创建新知识文档，不批量转换旧讲义。
- 未来旧内容迁移使用 dry-run mapping，确认后追加对象。
- 回滚时关闭知识文档 API；旧 editor/question/taxonomy 均不依赖 spike 表。

### 真实样例与测试

样例 lesson key 为 `math.g8.term1.lesson_012`。R1 有“定义/证明方法”；R2 保留同一 section ID 并移动“证明方法”，同时生成 A/B 两个新 section 和两条 `split_into` lineage。测试确认 R1 顺序未被修改。

### 未解决问题

- 独立 lesson registry 尚未建立，Phase 0 使用工作区唯一 lesson key。
- standard module 表未实现；section content 先保存 local block，模块引用只由 ADR 冻结语义。
- section 内多人实时协同不在 spike 范围。

## 3. Question Group Composition Spike

文件：`question_group_composition_schema_spike.sql`

### 复用关系

- 成员精确外键到现有 `question_revision(question_revision_id, question_id, workspace_id)`。
- 现有 `question_relation` 保留为 identity 图和迁移候选，不承担正式 composition revision。
- 题目正文、审核状态、来源和标签不复制到组表。

### 为什么不是重复 editor 或 question

组表没有 working draft、富文本、三变体、snapshot 或导出生命周期，因此不是第二套 editor。它只保存稳定组 identity、不可变成员组成、角色和顺序；每个成员内容仍由现有 question revision 管理，因此也不是第二套题目版本。

### 迁移与回滚

- 从 parent/child relation 生成候选，解析到 approved question revision 后才创建 composition。
- 缺 revision、跨 workspace、重复 order 或环形候选 fail closed。
- 回滚时旧 question relation/search/placement 继续工作；新增组数据保留待恢复。

### 真实样例与测试

样例由一个 material revision 和两个 child revision 组成 C1。数据库确保一个 composition 最多一个 material、成员顺序唯一、成员 revision 精确。两个并发创建 revision 2 的请求恰好一个成功。

### 未解决问题

- “至少一个 child”是跨行聚合约束，正式实现由事务服务在提交前校验并由集成测试覆盖。
- `requires_material` 的题型规则由教研后续冻结。
