# ADR-03 Question Group / Revision Composition

- 状态：Accepted for Phase 0
- 日期：2026-09-02
- 范围：英语父材料、子题、组合题的稳定身份和版本固定

## 决定

采用：

```text
question_group                       稳定组 identity
question_group_composition_revision  不可变组组成版本
question_group_composition_item      精确 question revision 成员与顺序
```

不新增一份复制题目内容的 `question_group_revision`。组的业务变化是“哪些精确 question revision 组成这一组、角色和顺序是什么”；题目正文仍由现有 `question/question_revision` 管理。`composition_revision` 能表达该事实而不复制材料、题干、答案和解析。

## Identity 与成员

- `question_group_id` 在同一材料题/组合题生命周期内稳定。
- 可选 `external_group_key` 由可靠来源系统提供；不能用组标题或材料文本当 identity。
- composition item 固定 `question_id + question_revision_id`。
- `member_role` 初期为 `material` 或 `child`；每个 composition 至多一个 material，至少一个 child。
- item 有稳定顺序和可选 local label；顺序属于 composition revision。
- 父材料如果本身是现有 question，使用其精确 revision；不再复制 material markdown 到组表。

## 版本规则

- 任一父材料或子题升级，不会自动改变已有 composition revision。
- 要让组使用新 question revision，必须创建新的 composition revision。
- 新 composition 可以只升级一个 child，其余成员继续固定旧 revision。
- composition hash 由 group ID、成员 role/order、question ID、question revision ID 和 schema version 规范化计算。
- 内容完全相同的 composition 不创建重复 revision。
- approved composition pointer 与 current composition pointer 分离；R3 可继续生产使用，R4 可编辑或待审。

## 题篮与讲义

### 整组操作

- 题篮加入整组时固定 `question_group_composition_revision_id`，并可投影出成员列表用于显示。
- 讲义加入整组时固定 composition revision；snapshot 将组材料和子题按该 composition 的顺序物化。
- 后续组升级只显示“可升级”，不改变旧题篮 snapshot、handout revision 或 export。

### 单题操作

- 选题台允许从组内选择一个 child；此时固定该 child 的 `question_revision_id`，并记录 `source_group_composition_revision_id` 作为上下文 provenance。
- 如果该 child 解题必须依赖父材料，API 必须同时携带 material revision，或拒绝产生不完整单题。是否依赖材料由题目元数据/人工确认，不由界面猜测。

## 搜索合同

- 全局搜索返回一个 `question_group` 聚合卡片：材料摘要、子题数、命中成员和 approved composition revision。
- 同一组多个成员命中只返回一张组卡片；命中位置列表用于高亮。
- 选题台保留专业接口，可切换“整组”或“单题”操作，并查看每个成员的题型、难度、标签和审核状态。
- 单题仍可独立出现在专业结果；全局搜索默认避免把组成员拆成多张重复材料卡片。
- 搜索投影不是组真相；必须能从 composition revision 重建。

## 与现有 question_relation 的关系

- 现有 `question_relation(child/variant/related)` 继续作为稳定 question identity 图和旧导入兼容。
- 它不固定 question revision，不能单独承担正式组版本。
- 首次创建 composition 时可从 relation 图生成候选，但必须显式解析并固定每个 question revision。
- Phase 0 不删除、不重写 question_relation。

## 并发与迁移

- 创建新 composition revision 时锁 question_group 根并检查 `expectedCompositionRevisionNo`。
- 两个基于同一 expected revision 的并发更新只能一个成功。
- 旧数据迁移先按 parent + child relation 构建 dry-run 候选；存在环、重复 order、缺 approved revision 或跨 workspace 时 fail closed。
- 迁移只追加 group/composition；原 relation 保留，回滚应用后旧题目接口不受影响。

## 验收测试

- 材料 R1 + 子题 A-R2/B-R1 创建 composition C1。
- 只升级 A-R3 后，C1 不变；显式创建 C2，C2 只替换 A。
- 相同成员/顺序重复提交不创建 C3。
- 并发创建 next revision 恰好一个成功。
- 整组加入题篮/讲义固定 composition；旧 snapshot 在 C2 获批后不变。
- 单题加入保留来源组 provenance；依赖材料的 child 不允许失去 material。
- 全局搜索同组多命中聚合为一项；专业搜索仍能操作单题。

## Phase 0 未解决但不阻塞 spike

- 哪些题型默认 `requires_material=true` 的教研规则。
- 组级审核是否复用题目风险决定，留给 ingestion/risk 后续工作包。
