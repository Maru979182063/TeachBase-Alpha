# TeachBase 后端承接审计报告

日期：2026-09-04

承接任务：实施 Phase 2B 基础硬化（`019f6565-4ca6-7ce3-917b-58b961239a54`）

审计代码：`61fd6438d944484bf6d07bb0fed5ed71e055f8ab`

结论：**基础可以继续开发；四链持续生产与多人试用门禁仍开放。**

## 1. 本次审计回答什么

本次读取旧任务最近 30 个 turn 的用户要求、完成记录及相关实现说明，再核对合并后的代码、数据库迁移和实际测试。未声称逐条阅读该长任务的全部早期对话，也没有把旧助手提出的建议自动当作已批准的产品决定。

任务标题已经落后于实际进度。旧任务最终交付的是包含 Phase 2B、四链受保护基础、Java 后端 V001–V008 和 WP-01 的聚合集成。PR #4 的合并已完成；现在应从合并基线继续，而不是重新做 Phase 2B 或重复开发 working draft。

证据分为三类：

| 标记 | 含义 |
| --- | --- |
| 本轮实测 | 本轮真正执行的命令和读取的代码 |
| 历史证据 | 旧任务、已保存基线记录和历史 CI，不冒充本轮复测 |
| 后续建议 | 尚未实现、不能据此关闭门禁的工作包与验收要求 |

本轮交付承接审计、机器证据和独立续作分支。没有新增业务迁移，也没有改变生产链、模型、prompt、route、role 或 threshold。

## 2. 基线、仓库与 Git 事实

| 项目 | 结果 |
| --- | --- |
| Integration | `integration/repository-scope-clean-20260715` |
| 审计 SHA | `61fd6438d944484bf6d07bb0fed5ed71e055f8ab` |
| 第一父提交 | `b96a400daadd11fd496ecc47152861f3d5496dae` |
| 第二父提交 | `8e3de5952b76c8665213feeaf132be0eb397495a` |
| ancestor 检查 | `git merge-base --is-ancestor 8e3de595... HEAD` 返回 0 |
| 本轮远端分支核验 | `git ls-remote origin refs/heads/integration/repository-scope-clean-20260715` 与审计 SHA 一致 |
| 原 integration 基线 | detached、clean |
| 独立续作分支 | `codex/backend-continuation-audit-20260904` |
| PR | [TeachBase-Alpha #4](https://github.com/Maru979182063/TeachBase-Alpha/pull/4) |

当前会话的「教研基建」目录处于无首个提交的分支，存在大量既有暂存和未暂存材料。它不是上述 integration 的可审计开发基线。本轮没有修复它的 Git 历史，也没有改动它的业务文件；开发承接使用由明确 SHA 创建的独立 worktree。

历史记录报告以下 post-merge CI 成功，均针对 `61fd6438...`：

- [Backend Foundation Integration](https://github.com/Maru979182063/TeachBase-Alpha/actions/runs/33722881779)：Ubuntu、Windows、release baseline。
- [WP-01](https://github.com/Maru979182063/TeachBase-Alpha/actions/runs/33722885042)：Ubuntu、Windows。
- [Phase 2B](https://github.com/Maru979182063/TeachBase-Alpha/actions/runs/33722888095)：Ubuntu、Windows。

本轮 GitHub CLI 未登录，因此没有重新读取这些 run 的在线状态、日志或仓库保护规则。Git 远端引用读取成功与 GitHub API 可用是两回事。上述 CI 是历史证据；本轮本地结果见第 6 节。

## 3. 必须继承的产品和工程合同

1. Java 负责 canonical 业务写入；Python/Node 加工链通过受控产物和领域入口交付。一次性测试库中的测试写入不等同于生产链直写。
2. working draft 可变，autosave 不生成永久 revision；显式冻结才产生不可变版本，snapshot/export 固定精确 revision。
3. 三版本 key 为 `basic/common/advanced`，展示名为基础版/常用版/进阶版；兼容旧「常规版」。既有 overrides 数组顺序不能顺手重排。
4. taxonomy 是分类体系，知识正文属于按讲次组织的 knowledge document；section 的顺序、标题、正文属于文档 revision，不能放到可变的稳定 identity 上。
5. 普通 editor block 默认是本地内容。显式保存为可复用模块或受控导入才建立 standard module；模块可包含图片、表格、公式等，不能退化为纯文本模型。
6. 正式题组需要不可变 composition revision，固定成员的精确 question revision；现有 relation 图不能替代它。
7. 低危需留下可审计自动放行决定，高危/未知进入 S02；风险决定不得改写题目正文。该产品事实已冻结，完整实现尚未落地。
8. 导入重试、稳定题目 identity、内容 revision 去重是三个合同；不能合成一个万能 hash/key。
9. 已发布讲义和旧 snapshot 不随 latest 自动变动；升级引用必须明确进行。
10. 同 taxonomy 维度单主标签门禁保持开放；「副标签升主后旧主标签降级还是删除」尚未获最终决定。本轮不代选。
11. 生产 Java 维护注释使用中文，特别说明并发、事务、幂等、租约、原子落盘及清理。语义判断使用模型节点、显式 schema、来源证据与可审计输出；不新增正则或关键词语义规则。

合同来源：`docs/architecture/phase0_contract_package.md`、ADR-01 至 ADR-04、`docs/architecture/wp01_editor_working_draft_implementation.md`，以及旧任务对应用户要求。历史 Phase 0 的「当前允许 WP-01」描述属于当时阶段记录，不能被解释为今天还没做完 WP-01。

## 4. 当前真实能力

代码目录有 12 个 Java 模块，生产迁移为 V001–V008。逐条迁移统计为 44 个 `teachbase_app` 建表声明；这不是旧 Runtime 的 43 表，也不是早期 survey 的 42 个候选目标表。

| 领域 | 当前实现 | 本次判断边界 |
| --- | --- | --- |
| 基础设施 | canonical config、兼容入口、原子 artifact 写入、并发清理、架构门禁 | 本轮 Phase 2B 复测通过 |
| 身份与成员 | 用户档案、workspace membership、角色字段、学科与学段组合 | 有业务归属，不代表有可信登录和完整动作权限 |
| 文件与来源 | file/version、source document/region、hash 与相对存储键 | 文件登记不等于用户上传及对象存储闭环 |
| 题目 | identity、不可变 revision、来源观察、生产指针、基础检索 | 已有入口不等于 ADR-04 全部落地 |
| 审核和 taxonomy | review case/decision、体系版本、节点、别名、revision 标签关联 | 风险自动放行与单主标签仍缺 |
| Release Seed | 已人工批准包的校验、入库、item 处理和恢复基础 | 业务前提是人工审核证据齐全，不能复用为所有四链原始产物的放行口 |
| 题篮与讲义引用 | 题篮草稿、checkpoint、snapshot、精确题目引用 | 正式题组 composition 尚未实现 |
| Editor WP-01 | working draft、CAS、mutation 幂等、checkpoint、迁移和回滚 | 本轮 21 项数据库/API 验收通过 |
| Snapshot / Export | 固定 revision、渲染与 worker 基础 | 本轮未重新运行完整 HTML/DOCX/PDF 导出门禁 |
| 四链控制基础 | registry、manifest、dry-run、保护执行、恢复与 ops 证据 | 本轮 107 项组合测试通过；持续生产仍 BLOCKED |
| 知识文档/标准模块/统一搜索 | ADR、spike 或规划 | 未发现对应正式领域表；不得当作已完成产品 |

## 5. Findings 与开发影响

严重程度按对应使用场景判定。以下主要是已知未完成能力，不是声称 PR #4 引入了回归。

### F-01：可信身份和动作级权限尚未闭合（P1，多人试用门禁）

`EditorDocumentController.java:62` 的读取入口仍接受客户端 `actorUserId`；`QuestionService.java:265` 只核对 workspace 存在及该 actor 是否活跃成员。当前 POM 和源码没有 Spring Security 请求身份链。调用方知道一个有效成员 ID 时，成员校验本身不能证明调用人就是该成员。

另外，`TaxonomyService.java` 的 activate/assign 复用成员检查，不能据此宣称 viewer/editor/reviewer 等动作权限已经完整落实。部分接口有专门角色规则，不代表所有接口均已覆盖。

后续应接入可信 actor 解析、统一拒绝客户端冒名、按操作校验 workspace 角色，并覆盖停用账号、跨 workspace 和越权写入。可先冻结身份适配端口；本轮不擅自选定 OIDC 供应商。

### F-02：四链通用 ingestion 边界未完成（P1，持续生产门禁）

`QuestionService.java:59` 的 `importBatch` 是一个事务内循环调用，尚不是 ADR-04 的 durable batch/item checkpoint。`ReleaseSeedPackageValidator.java:130` 要求每题已有 approved review 和 reviewer/time/policy，属于特定已审包合同。

因此，「有 import-batch」和「有 Release Seed worker」不能推出「四条链已可无人值守持续入库」。需要单独承接统一 envelope、请求幂等、item 账本、错误分类、恢复和领域端口编排。

### F-03：ADR-04 稳定 identity 与现有来源键实现有差距（P1，新导入包前置）

`JooqQuestionRepository.java:76` 以 `(workspace, source_system, source_key)` 处理冲突；随后仍按相同来源键查找 identity。`external_key` 被保存，但不是当前这段识别路径的优先匹配键。`QuestionService.java:148` 的内容 hash 也有现行字段集，不能直接替换成新 manifest 声称的 hash。

当同一可靠 external question key 因来源 locator 改变而换了 source key，当前行为不能保证继续命中同一 question。这个差距相对于新 ADR-04 合同成立，不等于旧 Release Seed 的既有合同失效。

下一包必须先定义并测试新旧 adapter 的 identity 兼容，不得通过改拼接方式或语义相似度自动合题。更换 profile 而正文不变应只追加 provenance observation。

### F-04：低危自动放行仍是合同，未形成完整状态链（P1，自动生产门禁）

`QuestionService.java:123` 只接收 `unreviewed/pending_review`；V005 的 `ck_review_decision_source` 仅允许 `human_ui/release_seed/api`，没有 ADR-04 中的 risk-auto 决定链。

直接让 manifest 自报 `low` 然后写 approved 会绕过合同。需要可信风险来源、policy version、evidence hash、精确 revision/hash 前置和追加式决定；unknown 必须进入审核。报告未替项目设定任何模型阈值或风险关键词规则。

### F-05：标签数据库约束不能保证每维度只有一个 primary（P1，标签和搜索 schema 门禁）

V005 `question_taxonomy_link` 的唯一约束位于第 204 行，键为 `(question_revision_id, taxonomy_node_id, relation_type)`。它可以阻止同一节点重复关联，不能阻止不同节点同时为 primary。服务 assign 的枚举校验也没有补足这一不变量。

保持 `BLOCKS_TAG_SCHEMA_AND_SEARCH` 开放。先确认维度与版本边界、主副切换语义，再做事务、数据库约束、存量冲突审计及并发测试。不能自行把旧主标签删除或降级来获得绿色结果。

### F-06：知识文档、正式题组和统一资产搜索还未生产化（P2，对应工作包前置）

ADR-02/03 和 `teachbase_phase0_spike` 已把核心方向表达清楚，但 V001–V008 没有 knowledge document、stable section/composition、standard module 或统一搜索正式表。

题目专业检索与 taxonomy 解析已经存在，不等于包含知识文档、模块、讲义、题目和题组的全局搜索。未来模块/搜索包需受 F-01、F-05 约束，知识文档本地内容基础可独立切片。

### F-07：生产 readiness 报告目前是显式静态阻断清单（P2，后续验收工具改造）

`tools/build_final_chain_production_readiness_gate.py:12` 保存五项 blocker，`build_report()` 固定输出 BLOCKED；foundation gate 明确断言这个状态继续存在。

这是当前基础集成阶段的有意保护，不是伪造绿灯。后续实现真实能力时，必须同时为具体能力提供可验证证据，再让 readiness 按证据决定哪些 blocker 仍存在。只修改常量、删除 blocker 或把退出码变为 0 都不是生产完成。

### F-08：后续联调与运维仍有独立边界（P2，试用/发布前置）

前端 409 恢复体验、正式上传/下载鉴权、完整权限、生产容量、监控和恢复演练不能由本轮基础门禁代替。旧 editor draft 的 contract/drop 继续单列，不能为了清理表而提前删除。其他任务的数据导入和原型成果本轮未逐项验收，不推断实际已批准种子数。

## 6. 本轮测试与可复现证据

本轮环境：Windows、Python 3.12 隔离 venv、Java 21.0.12、Maven 3.9.16、Node 24.18.0、测试 PostgreSQL 18.4。历史 CI Node 为 20；本轮没有声称覆盖同一 Node matrix。

| 命令/步骤 | exit | 本轮结果 |
| --- | --- | --- |
| `python -m venv .venv` 与 `python -m pip install -e ".[dev]"` | 0 | 独立环境安装成功 |
| `npm ci --no-audit --no-fund` | 0 | 依赖安装成功；出现 embedded-postgres postinstall 未在 allowScripts 登记提示，后续真实数据库启动和测试均成功 |
| `node tools/run_java_foundation_maven.mjs -q clean package` | 0 | 7 个 suite、14 tests、0 failure/error/skipped，含 Modulith 边界 |
| `node tools/check_java_chinese_comments.mjs` | 0 | 212/212，未翻译注释块 0 |
| `node tools/audit_java_foundation_database.mjs` | 0 | 一次性旧 Runtime 测试库生成 43 表库存 |
| `node tools/validate_java_foundation_survey.mjs` | 0 | 旧表映射 43/43；prototype/environment 部分仍核验受控历史资料 |
| `python tools/run_modularization_phase2b_gate.py` | 0 | 7 子门禁返回预期结果；config parity 4、artifact concurrency/cleanup 4、边界 7、English 7、DOCX 11 |
| `python -m pytest tests/test_semantic_role_golden_parity.py -q` | 0 | 1 个测试比较 18 份 Golden 文件 |
| `node tools/run_wp01_v008_migration_gate.mjs` | 0 | 12/12，空库及 V007 升级、旧行不变、writer fence |
| `node tools/run_wp01_editor_working_draft_gate.mjs` | 0 | 21/21，100 autosave、CAS、幂等、并发冻结、回滚、跨 workspace、清理 |
| `python tools/run_final_chain_foundation_integration_gate.py` | 0（纠正日志位置后） | 14 个子命令成功，其中组合 pytest 107 passed；PDF English 从 HEAD 重建通过；active absolute paths 检查通过 |

重要读数：100 次 autosave 后 draft version 101、永久 revision 0、checkpoint 1；两个并发保存恰好一成功、一 409；并发 preview 只创建一份 revision。数据库测试清理通过。

Phase 2B 内的 legacy CLI 预期退出码为 20，表示原有 dataset review-required 合同被保留，不是 paid model 执行失败；也不能把该项描述成真实数据质量已验收。

### 首轮失败与纠正记录

1. 直接运行 survey validator 首次得到 ENOENT，因为新 worktree 尚未生成 database inventory。按正式上层 gate 的顺序先运行 database audit 后通过。没有复制开发机旧库存冒充新生成。
2. 四链基础 gate 首轮 exit 2：审计自己在仓库根写入了两份 `.log`，导致 precleanup 将其视为未归类文件，并连带导致两项 sealed-manifest 测试失败（105 passed / 2 failed）。将日志移入既有忽略目录 `artifacts/ci`、恢复本轮生成的两份受控报告后重跑，107/107 通过。未放宽任何断言。
3. 测试会刷新两份已受版本控制的 PDF English recovery report。本轮将刷新副本存入审计证据，再恢复基线内容，避免在纯承接报告提交中夹带机器输出。

机器证据目录：`artifacts/ci/backend-continuation-audit/`，入口为 `evidence.json`。保存本轮 test report、首轮失败、Golden XML、Surefire XML 和日志；附 SHA-256 校验。它是本地产物，按现有政策忽略，不声称已上传 CI。

没有在本轮运行完整 aggregate、完整 renderer、Release Seed live gate、长期压测或 Ubuntu jobs。历史 release-gate 的 68/71 债务不因本轮测试而关闭。Survey 的 43 旧表/42 候选表及 Java17 历史环境字段也不代表当前生产 schema 或本轮 Java 运行时。

## 7. 建议的后续工作包

以下是排序建议，不是假定已经完成或获准发布的功能。

| 顺序 | 建议切片 | 完成时必须证明 |
| --- | --- | --- |
| 1 | 四链通用 ingestion 接口与持久化批次基础 | 请求 ID 幂等、hash 冲突、item 状态、恢复、身份/内容去重、审计与隔离 |
| 2 | 可信风险结果与放行边界 | low/high/unknown 的真实状态转换；未可信输入 fail closed；旧 approved 内容不变 |
| 3 | 四链逐条标准出口和 durable worker | 每链真实样本从标准 CLI 到 Java；kill/restart 恢复；没有 canonical 直写 |
| 并行前置 | 可信身份与接口动作权限 | 多人接入之前完成；不能等到搜索和共享资产都做完才补 |
| 随后 | knowledge document/section 与题组 composition | 稳定 identity、不可变 occurrence/composition、精确引用、旧 snapshot 不变 |
| 条件满足后 | 标签维护、标准模块、统一搜索 | 单主标签决定、ACL、模块显式创建、可重建搜索投影均有证据 |

如果近期目标是多人试用而不是加工链入库，第 1 项应调整为可信身份与权限。旧任务没有批准固定的 WP-02 编号或完整规格，本报告不把任何推荐名伪装为已冻结工作包。

### 第一个 ingestion 切片的建议验收

- 同 workspace/request ID/manifest hash 返回同 batch；同 ID 不同 hash 返回 409。
- 不同请求重复交付同一稳定题目和正文不新增 revision；profile 变化只追加来源观察。
- 有可靠 external key 时 source locator 变化不误建题；无可靠 identity 时不使用文本相似度自动合并。
- 每个 item 持久化状态、错误类型和完成结果；处理到任一 item 后重启可恢复，完成项不重复写。
- file/source/question/review 通过 Java 模块公开端口组织，不将 Release Seed 的人工审核前提移除。
- 缺少可信风险证据时保存候选并进入待审核路径，不能提前开启自动批准。
- 生产 runtime 未完整打通之前，`FINAL_CHAIN_PRODUCTION_READINESS` 继续开放；基础入库接口成功不等于四链生产验收完成。
- 测试覆盖正常、并发、重试、冲突、崩溃恢复、跨 workspace、回滚及旧 WP-01/snapshot 回归，维护注释中文化。

## 8. 承接结论与保留门禁

**承接审计完成。** 当前已合并基础可复用，本轮检查未要求重做 Phase 2B 或 WP-01。后续应按一个明确业务闭环推进，不能把受保护基础、ADR 或单入口可用写成整套后端生产完成。

保持开放：

- `FINAL_CHAIN_PRODUCTION_READINESS`：standard CLI、result emission、checkpoint resume、durable worker runtime、Java ingestion boundary。
- `BLOCKS_TAG_SCHEMA_AND_SEARCH`。
- `formal_authentication_and_acl`。
- `frontend_409_merge_experience`。
- `production_capacity`。
- `standard_module`、`unified_search`、`knowledge_document`、`question_group`。
- `legacy_editor_draft_contract_drop`。

本报告不宣告新的生产门禁关闭，也不宣告完整后端完成。下一工作包的选择与落实应继承上述证据和边界。

## 9. 真实样本补充

后续使用用户提供的数学教师版 DOCX 和授权 key 进行真实模型试跑，发现基础检出缺失部分运行依赖，以及图片留证、边界上下文组装等契约问题。具体修复、模型调用证据和内容审阅限制见 [数学 DOCX 真实样本试跑审计](docx_math_real_sample_audit_2026-09-04.md)。本报告第 6 节的基础测试记录不构成真实样本或生产加工完成的证明。
