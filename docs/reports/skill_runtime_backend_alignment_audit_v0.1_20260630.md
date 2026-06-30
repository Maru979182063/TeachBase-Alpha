# Skill / Runtime / 后端对齐审计 v0.1

更新时间：2026-06-30

## 1. 审计目的

本次审计聚焦三个问题：

1. 当前 skill 与 runtime 的输出语义，是否能被现有后端模型稳定承接。
2. 当前后端表、接口、投影层之间，是否存在结构冲突或语义缩水。
3. 是否需要现在就修正后端设计，还是维持主范式、只做局部补强。

## 2. 审计结论

结论可以先说在前面：

- 当前主范式没有跑偏。
- “题目是基础内容对象，讲义骨架是主挂载结构，知识点是语义映射层”这条路线仍然成立。
- runtime 的导入、发布、考点继承与单题 override 主逻辑是通的，三轨基线验证已通过。
- 需要修正的不是总体架构方向，而是几个会影响后续扩展和审计追溯的结构细节。

## 3. 已确认对齐的部分

### 3.1 结构主挂载方向是对的

- `task_revision` 通过 `source_node_revision_id` 绑定到讲义骨架节点。
- `source_node_checkpoint_link` 与 `task_checkpoint_override` 已区分“节点默认考点”与“单题覆盖”。
- `getCheckpointCodesForTaskRevision()` 已实现“节点默认继承 + 单题 add/remove/replace override”。

### 3.2 Postgres 主路并非只有早期 validation 表

- 当前 Postgres store 会依次执行：
  - `20260623_runtime_backbone_validation.sql`
  - `20260623_postgres_sole_source.sql`
  - `20260624_three_track_validation_alignment.sql`
  - `20260624_three_track_final_review_hardening.sql`
- 因此结构表、考点映射表、学科扩展表并不是完全缺失，而是已经进入 normalized tables 路径。

### 3.3 三轨核心语义已被自动验证

- 已执行 `npm run test:three-track-baseline`，整套三轨基线通过。
- 这说明以下链路当前可用：
  - 导入 lesson draft bundle
  - 审核与发布解耦
  - 节点默认考点继承
  - 单题 override
  - 题库收录
  - 讲义装配
  - component rerun

## 4. 发现的问题

### P1. `lesson_revision.bundle_jsonb` 会在同步后丢失 richer task 级证据字段

当前导入时，原始 bundle 会先完整写入 `lesson_revision.bundle_jsonb`。但紧接着 `syncLessonRevisionBundle()` 会用 runtime 重建后的 bundle 覆盖回去，而重建后的 task 只保留了一套较小的 canonical 字段：

- `local_task_id`
- `source_node_local_id`
- `question_type`
- `stem / answer / explanation`
- `difficulty_*`
- `checkpoint_codes`
- `checkpoint_override`
- `subject_tags`
- 一个被收缩过的 `source_refs_json`

其中 `source_refs_json` 在重建 bundle 时只保留：

- `component_id`
- `page_no`
- `crop_artifact_id`

这意味着如果上游 skill / runtime 结果里已经带有更丰富的字段，例如：

- `question_image`
- `stem_image`
- `analysis_image`
- `line_source`
- `uncertain_spans`
- `risk_spans`
- 更完整的 `bbox`
- 其他视觉证据 refs

这些内容不会继续稳定保留在 lesson revision 的“当前 bundle 视图”里。

影响：

- 后续如果有人把 `lesson_revision.bundle_jsonb` 当成“当前权威导出包”，会拿不到完整 skill 证据。
- 审计 UI、重放调试、问题追责会出现“组件里还有，bundle 里没了”的割裂。

建议：

- 不要再把 `bundle_jsonb` 视为只靠 runtime 重建即可完全回放的唯一视图。
- 至少补一层 `raw_bundle_jsonb` / `ingest_bundle_jsonb` 与 `normalized_bundle_jsonb` 区分。
- 或者在 task 级 canonical 输出里正式纳入可追溯的视觉证据字段，而不是只留最小来源引用。

### P1. `task_subject_ext` 的运行态实现已经收缩成“每题仅一条扩展”

设计草案中，`task_subject_ext` 更接近“同题可挂多个插件扩展”的模型；但当前运行中的 Postgres migration 是：

- `task_subject_ext.task_revision_id text primary key`

这会直接把运行态限制成“每题只能有一条扩展记录”。

影响：

- 现在单学科单插件还没问题。
- 一旦后面出现“同题既要学科插件结果，又要独立质量插件、标注插件、知识点建议插件”的情况，就会顶掉。

建议：

- 尽早把运行态主键改成复合键，至少与草案保持一致：
  - `(task_revision_id, plugin_id)`
- 如果短期不改，也要明确写进文档：一期只支持“每题单插件扩展”。

### P2. `risk_flags` 在草案与运行态之间已经发生语义缩水

草案中 `task_subject_ext.risk_flags` 是 `jsonb`，更适合存结构化风险信息。
当前运行态 migration 中它是 `text[]`。

影响：

- 只能存简单字符串列表。
- 如果后续要挂风险来源、严重度、命中字段、证据引用，就会不够用。

建议：

- 如果风险层只需要简单标签，可以暂时不改。
- 如果准备承接 `uncertain_spans / risk_spans / quality gate` 的结果，建议尽早改回 `jsonb`。

### P2. `task_projection` 和 `question_bank_item_revision` 目前只适合作为消费层，不适合作为再加工主源

当前投影层与题库修订层都已经是扁平化结构，保留的是：

- `stem / answer / explanation`
- `checkpoint_codes`
- `subject_tags`
- `source_refs_json`
- `difficulty_*`

但没有完整保留：

- `source_node_revision_id`
- `checkpoint_override`
- 插件级扩展上下文
- richer 视觉证据

这本身不算 bug，因为它们本来就更适合作为：

- 搜索层
- 题库消费层
- 导出消费层

但风险在于，如果后续业务开始直接把：

- `task_projection`
- `question_bank_item_revision`

当成“再编辑、再回流、再拼装”的主源，就会把结构语义和审计信息丢掉。

建议：

- 保持现在的定位：它们是投影层，不是事实主源。
- 后续所有需要结构回放、视觉追溯、插件重跑的能力，都应回到：
  - `lesson_revision`
  - `task_revision`
  - `component_revision`
  - `task_subject_ext`

### P2. `material_item` 现在只能装题库题目，不能装非题组件资产

当前 `material_item` 结构固定引用：

- `question_bank_item_revision_id`

这意味着未来你想开放的这些内容：

- 公司 logo
- 讲义头图
- 常用说明块
- 非题组件模板
- 教师自建可复用组件

都不能直接进入同一套讲义装配层。

影响：

- 当前题目拼装没问题。
- 未来“组件库 + 教师搭板”会卡在 schema 层，而不是前端层。

建议：

- 现在不必重做 `material_build`。
- 但建议预留统一装配引用范式，例如：
  - `item_type`
  - `item_revision_id`
  - 或者题目、组件分路字段

否则后面扩展时要改表、改接口、改导出链路。

## 5. skill / runtime 输出与后端承接情况判断

### 5.1 当前能承接的

- lesson 结构主挂载
- 节点默认考点
- 单题考点 override
- 学科 track / difficulty 基线
- component crop 与 source refs 的基础留存
- 题库收录与发布边界

### 5.2 当前承接得不够完整的

- `line_source`
- `question_image / stem_image / analysis_image`
- `uncertain_spans`
- `risk_spans`
- 更完整的 visual refs
- 更细的 plugin/risk 结构化结果

这些信息并不是完全没有地方放，而是：

- 有的只在原始 bundle 导入瞬间存在
- 有的只在 `component_revision.source_refs_json` 里旁路保留
- 有的只在报告或中间文件里存在
- 没有进入一套稳定、统一、可查询的 canonical backend contract

## 6. 是否需要修改后端设计

结论：

- 不需要推翻当前后端主设计。
- 需要做 4 个定向修正。

建议优先级：

1. 区分 raw bundle 与 normalized bundle，避免 skill 证据在同步时被冲掉。
2. 把 `task_subject_ext` 从“单题单扩展”改回可多插件挂载。
3. 明确 `task_projection / question_bank_item_revision` 只做消费投影，不再承接事实主源职责。
4. 为 `material_item` 留出非题组件资产入口。

## 7. 最终判断

从你当前的一期目标来看，后端不需要返工重构，现有主路线可继续推进。

真正要补的是“口子”：

- 给 richer skill 输出留正式归档口子
- 给多插件扩展留口子
- 给组件库/非题资产装配留口子

如果这三处不补，短期还能跑，但你后面一旦往：

- 审计工作台
- 组件库
- 教师搭板
- 多插件评估
- 视觉证据追溯

这些方向推进，就会开始频繁碰到“当前链路能用，但底层语义不够稳”的问题。
