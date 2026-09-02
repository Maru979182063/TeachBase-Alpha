# ADR-02 Knowledge Document / Section / Handout Reference

- 状态：Accepted for Phase 0
- 日期：2026-09-02
- 范围：以讲次为单位的知识结构文档、稳定 section 与讲义引用

## 领域边界

- `taxonomy` 只表达分类树、别名和版本化分类坐标，不保存知识文档正文。
- `knowledge_document` 以一个讲次为基本单位；稳定 ID 不因正文修订变化。
- Phase 0 用工作区内唯一 `lesson_key` 绑定讲次，例如 `math.g8.term1.lesson_012`。未来若建立独立 lesson registry，只追加 `lesson_id` 并回填，不改变 document ID。
- `knowledge_document_revision` 是完整 section 树的一次不可变版本。
- `knowledge_section` 是跨文档版本稳定的 section identity；标题、位置和内容属于 revision。

## Section 版本语义

| 操作 | 稳定 identity | lineage |
| --- | --- | --- |
| 修改标题/正文 | 保留 section ID | 新 revision 中记录 updated |
| 移动 | 保留 section ID | parent/order 在新 revision 改变 |
| 新增 | 新 section ID | created |
| 删除 | 旧 ID 不出现在新 revision | retired，不物理删除 identity |
| 拆分 | 产生多个新 section ID | 旧 -> 新，`split_into` 多条边 |
| 合并 | 产生一个新 section ID | 多个旧 -> 新，`merged_into` 多条边 |

拆分/合并不能偷偷复用其中一个旧 ID，因为这会让旧讲义的 section 引用语义不确定。lineage 只用于升级建议，不自动重写旧引用。

## Section 内容

- local block 是该 knowledge revision 内的结构化内容，没有跨文档资产身份。
- standard module reference 只有在用户显式“保存为可复用模块”或受控导入后出现。
- 删除 local block 不影响任何模块；解除 module reference 不删除模块。
- Phase 0 schema spike 只定义 section content 和引用槽位，不创建 standard_module 表。
- section 可包含文本、图片、表格、公式、思维导图、题目或模块引用；二进制仍由 file version 管理。

## Handout 引用模式

四种模式均有明确用途，但允许出现的阶段不同：

| 模式 | working draft | immutable handout revision | snapshot |
| --- | --- | --- | --- |
| `pinned` | 允许 | 允许，必须精确 revision/section | 物化内容 |
| `follow_approved` | 允许 | 禁止动态指针；发布时解析成 pinned | 禁止 |
| `detached_copy` | 允许 | 允许，正文复制并保留 provenance | 物化内容 |
| `local_override` | 允许 | 允许，固定 base revision + override patch/hash | 物化合并结果 |

### 发布解析

1. 读取 handout working draft 的 reference。
2. `pinned` 验证目标 revision/section 存在。
3. `follow_approved` 解析为当时 `approved_revision_id`；没有 approved revision 则 fail closed。
4. `detached_copy` 不再读取来源，只保留 source document/revision/section provenance。
5. `local_override` 固定 base revision、override payload 和合并后 hash。
6. 创建新的 immutable handout revision；snapshot 只读取该 revision 的解析结果。

旧讲义默认保持原 pinned revision。知识文档新版只产生“可升级”提示；制作新讲义或新版本时，用户才能显式按 section 选择升级。拆分/合并只提供 lineage 候选，不自动替换。

## 为什么不是另一套 editor

knowledge document 复用 Tiptap/结构化 block schema、校验器、hash 工具和 working-draft 模式，但不复用 `editor_document` 根表：

- editor 的三产品变体、teacher/student snapshot 和导出生命周期属于讲义。
- knowledge document 的 lesson binding、section identity、split/merge lineage 和 section 引用属于知识内容维护。
- 共享内容格式库，不共享聚合生命周期，避免两套 JSON 解释器同时演化。

## 迁移与回滚

- Phase 0 不自动把现有讲义变成 knowledge document。
- 首批 knowledge document 通过受控导入或人工创建；导入保存原 source provenance。
- 若以后识别出旧 editor 内容，先生成 dry-run mapping，人工确认后追加新对象，旧 editor 不变。
- 功能关闭时只停止新 API；新表是追加式，旧讲义和导出不依赖它，可直接回滚应用版本。

## 验收测试

- 同一 workspace/lesson_key 只有一个稳定 knowledge document。
- revision 2 移动 section 后，section ID 不变，旧 revision 顺序不变。
- split/merge 创建新 section ID 和完整 lineage；旧引用仍解析旧 section。
- follow_approved 发布时固定，目标升级后旧 handout revision/snapshot hash 不变。
- detached_copy 在来源归档后仍可渲染；provenance 保留。
- local_override 可重放得到相同 merge hash；base revision 缺失时 fail closed。

## Phase 0 未解决但不阻塞 spike

- 独立 lesson registry 的最终表结构。
- standard module 的 payload 和审核状态机。
- section 级协同编辑/CRDT；当前仍使用聚合级 optimistic lock。
