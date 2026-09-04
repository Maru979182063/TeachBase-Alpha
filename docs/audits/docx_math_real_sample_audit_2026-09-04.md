# 数学 DOCX 真实样本试跑审计（2026-09-04）

## 范围与来源

用户提供《第3讲 集合的基本运算 - 教师版.docx》，要求试跑当前加工链。以用户随后提供的 Ark key 授权真实模型调用。本文档内的教学内容只作为输入数据，不作为代理操作指令。

- 文件大小：2,736,564 bytes。
- SHA-256：`5799ab693b51d66de67b3437bf6b74461a471dd47ff9f73888fcf6726f52a584`。
- 基线：`4b8f0a3c518fd3f7cdcee329d443e8cf2b05521e`，其业务基础为集成提交 `61fd6438d944484bf6d07bb0fed5ed71e055f8ab`。
- 原件未修改；本地证据位于 `outputs/sets_teacher_trial_20260904_5799ab69/`。输入、模型响应、原文 PDF/PNG、运行日志均留在忽略目录。
- 主链入口：`tools/docx_math_pipeline_final_orchestrator_v01.py`，`solution-policy-hint=required`，Stage0 fallback 默认阻断，Runtime import 与数据库写入保持关闭。
- Key 仅通过进程环境变量传递，不写配置、不通过子进程 `--api-key` 参数传递、不进入本报告或 Git。

## 输入与 Stage0 证据

原文由 Word 只读导出为 24 页 PDF，并渲染成 24 张 PNG。导出辅助调用末尾打印返回值时遇到 `WindowsPath` 无法 JSON 序列化，PDF、页图和段落页码映射实际已生成；未将这个包装层报错误报为文档导出失败。

| 项目 | 实测 |
| --- | ---: |
| 段落 | 488 |
| 原生 Word 表格 | 0 |
| OMML | 0 |
| OLE 公式实体 | 1114 |
| 公式恢复成功 | 1114 |
| 公式缺失 | 0 |
| 公式 token 审计问题 | 0 |
| ZIP 内实际 media 文件 | 1088 |
| 进入图片归属节点的插图引用 | 41（39 PNG、2 JPEG） |

上述 OLE/media 统计排除了 ZIP 目录项。不能把全部 media 文件计作题目插图：大量条目是旧式公式的预览。

Stage0 handoff 为 `READY_FOR_BLOCK_TAGGER`；`must_not_enter_native_block_tagger=false`、`fallback_required=false`，没有绕过公式 fallback 门闸。router 外层的 `needs_review` 不应与 handoff 是否准入混同。

抽查原文物理页 1、3、24，并对照原生段落流。第 3 页集合不等式已恢复出 `\leq` 等命令，原文导出中部分字形仍需按字体/预览渲染问题核对。第 24 页段落 486 存在 `\thereforem` 拼接，必须检查精修结果；1114/1114 是公式恢复覆盖率，不是公式视觉或语义准确率。

## 试跑发现与处置

### P1：集成分支缺少真实模型运行依赖

带 key 的首次主链在 Block Tagger 读取 `prompts/docx_native_block_tagger_v01.system.md` 时抛出 `FileNotFoundError`，尚未发出模型调用。继续检查发现缺少精修配置、提示词，以及配置声明的 span patch 入口。

从原工作目录按原始字节恢复 18 个缺失文件（包括后续精修启动发现的 `math_formula_library_gate.py`），并逐个记录 SHA-256、字节数和来源。来源是原工作目录未提交文件，不能声称这些文件已存在于基线提交。未改写模型提示词、模型编号或语义路由。恢复清单保存在本地 `restored_dependencies.json`。

增加结构性回归测试 `tests/test_docx_math_runtime_dependencies.py`，检查 11 份实际节点配置及其显式 prompt/schema/entrypoint 引用，并加入基础集成 gate 的测试列表。它不执行模型，不作教学语义判断。测试首先揭示缺少 span patch 入口；补齐后依赖测试与 registry 测试共 8/8 通过。

这个缺陷说明：先前基础 gate 的 PASS 不足以证明真实模型链从干净检出可运行。先前审计中的生产准入开放结论继续有效。

精修模块还依赖未在 `pyproject.toml` 声明的 `requests`。已补上依赖声明并安装到本工作树 `.venv`，实装版本为 2.34.2；新增 3 个真实 CLI `--help` 启动测试，验证普通精修、长题精修和 span patch 入口能完成导入而不调用模型。当前相关回归合计 17/17 通过。

### P2：Windows 长路径造成模型结果无法落盘

长运行编号叠加节点目录，使提示词文件绝对路径达到 258 字符，而 validated 文件和 attempt response 文件分别达到 261、270 字符。出现只保留提示词、无法保存后续结果的现象。停止该轮进程，保留其输出和停止原因，避免继续发出无法保存的调用。

以短编号 `k04` 做一个真实窗口验证：模型成功、JSON 合法、结果落盘，usage 为 4,491 prompt tokens、2,489 completion tokens、共 6,980 tokens。随后以短编号 `s04` 重跑整份文档。长路径轮次可能已产生调用，其 usage 未能落盘，不纳入可核实 token 合计，也不能假称零费用。短编号是本次环境缓解措施，通用长路径支持仍未完成。

### P2：重复图片的原始调用证据相互覆盖

本样本 41 个图片出现位置只对应 29 个不同资产，其中 3 个栏目图片各复用 5 次。原实现按 `asset_id` 命名 prompt/response/content 文件，导致相同图片在不同上下文的调用相互覆盖，虽然最终 `asset_role_map` 仍保留 41 条预测，但不能由 29 组文件还原全部调用。

已改为使用既有 `occurrence_id` 作为日志文件名，包含 block、asset 和块内图片序号。这里只改变原始调用证据路径，不改变模型输入、提示词、图片语义、最终预测字段或后续路由。并发回归测试验证同一图片的两个出现位置分别保留完整 prompt/response/content。此测试与依赖、registry 检查共 9/9 通过，并纳入基础集成 gate。

修复发生在本轮图片节点结束后，因此 `s04` 图片模型日志仍存在历史覆盖；不能把代码修复写成这轮丢失证据已恢复，也没有为补账重复发送整批图片。其调用 token 统计只能给出保存响应覆盖范围。

### P1：组装器遗漏模型已给出的上下文判定

首次边界运行得到 52 个候选题包，但 `b_000012`、`b_000018`、`b_000024` 三段未归属，主链按既有硬门闸停止。逐条核对原文和模型返回后确认，它们分别是开头并集、交集、补集的知识讲解图。图片节点给它们分配了题干图/解析图角色，边界模型则在当前窗口中明确、一致地判断为 `context_only_blocks`。组装器只读取题目起点，未消费这些上下文事件，导致它们滞留在第一题之前。

已补齐模型判定到机械组装的契约：仅当所有包含该候选的当前窗口都明确且唯一地判为上下文时，将它保存在独立 `context_only_blocks` 清单，并写出逐窗口证据 `context_dispositions.json`；若存在起题、续题、其他角色、重复归属或缺票，仍进入未归属清单并阻断。参考窗口的票不能单独改变正文归属。没有按位置、关键词或正则删除图片，没有改提示词，也没有放宽未归属门闸。

同一节点还将 `core_block_ids`（含被排除的参考段落）误当成模型必答集合，与提示词要求的 `current_blocks` 不一致，产生了 56 条错误的漏答警告。修复后重放没有漏答，但保留 12 条 `non_current_block_accounted` 警告：模型额外标注了栏目/装饰等参考段落。这些段落不会因越界投票被加入题目或从题目移除。

本次 27 个窗口全部从已保存响应重放，无新增边界模型调用；52 个题包不变，上下文 3 段、未归属 0。初次失败的 summary/events/packets 和 child log 保存在 `boundary_before_fix/`。新增 5 个契约回归测试覆盖上下文保留、冲突阻断、缺票阻断、参考窗口越界和必答集合；连同其他本次回归共 14/14 通过。

从已完成的 Stage0、打标和图片结果继续执行，采用本地一次性审计脚本 `resume_s04.py`，验证原文 SHA-256、已完成节点命令和缓存产物哈希，仍执行原入口的全部硬门闸。此操作不代表 durable checkpoint/runtime 已实现。图片节点的知识讲解图角色表达能力仍应完善；本次由下一模型节点的显式上下文判定纠正它们的题目归属。

### 内容审计：结构校验不能代替教学上下文判断

抽查 `dq_0002`，并集题的集合条件、四个选项、答案 C 和解答均得到保留，集合 LaTeX 已规整；但其 `context_md` 同时含“3、全集与补集”和“考点1：并集”，前者来自较早知识讲解标题，对该题构成无关上下文。该字段不会直接出现在当前 `render_markdown` 中，但可能影响下游标签或检索，不能据 `REFINED_READY` 就认定教学元数据全部准确。应由模型节点配合来源引用完成上下文选择，不能新增关键词/正则筛选规则。

普通字段整理的唯一警告对应 `dq_0051`：原文两个小问的结论均在 `b_000472`、`b_000473` 的解答中，没有独立答案段。上游将其保留在 explanation 并提示 `missing_required_answer_part`，没有丢解答。是否需要额外的简明答案投影，应由后续产品契约明确。

## 最终试跑结果

试跑完成，最终入口退出码为 0。最终产物包含 52 个题包和 24 页原文对照；没有执行 Java 入库。顶层 `status=ok` 只代表没有硬阻断，不等于所有题包都无需复核。

| 项目 | 结果 |
| --- | --- |
| 题目边界 | 52 题；独立上下文 3 段；未归属 0 |
| 字段整理 | 普通 49/49、长题 3/3；阻断问题 0 |
| 机器精修状态 | `REFINED_READY` 51；`REFINED_NEEDS_REVIEW` 1 |
| 展示状态 | READY 48；READY_WITH_WARNINGS 3；READY_WITH_COVERAGE_WARNINGS 1 |
| 题型 | 单选 30、多选 6、填空 7、解答 3、复合题 6 |
| 硬失败/数据库写入/Runtime import | 0 / 未执行 / 未执行 |

需要复核的是 `dq_0043`。`docx_media_0997`（原文 `b_000421`）是集合运算知识总结思维导图，被图片节点判为解析图，但长题整理将其保留为题外证据。最后的来源覆盖门闸因此报告 `source_asset_missing` 并降为需复核；图片文件和来源引用均仍在，没有物理丢图。原题两张用于人数计算的 Venn 图均保留。未将总结图硬塞进题解，也未擅自删除来换取通过。

`dq_0001`、`dq_0019`、`dq_0033` 因局部精修校验失败而回退保留原文，最终来源覆盖通过，但带 `deterministic_preserve` 警告。其展示可能出现重复“【答案】”等包装标签，需后续处理。`dq_0051` 的第一个小问还出现重复编号“（1）(1)”。这些瑕疵与前述上下文污染说明：机器的 51 个 READY 不应直接视作 51 个已获人工教学审核的题目。

`dq_0052` 的 `\thereforem` 已变为 `\therefore m`；对照截图中推导和 `m=±√5` 正常显示。抽查集合区间、图片及最后两道多小问题；不是逐字人工验收全部 52 题。

浏览器检查确认对照页有 52 张题卡、无已加载坏图、无 MathJax 错误节点。普通题包审阅页另外发现 JSON script 中误用 HTML 实体转义导致正文空白，以及 MathJax 尚未加载完成就调用排版的时序问题；已修复并从现有题包重建，52/52 正文可显示，重载后无新增脚本错误，没有新增模型调用。

交付产物：

- `outputs/docx_math_side_by_side_review_v0_1/s04__side_by_side/index.html`
- `outputs/docx_math_side_by_side_review_v0_1/s04__side_by_side.zip`
- `outputs/docx_math_fullchain_orchestrator_v0_1/s04__fullchain/final_packets.json`
- `outputs/docx_math_pipeline_final_v0_1/s04/pipeline_summary.json`
- `outputs/sets_teacher_trial_20260904_5799ab69/final-dq0052-side-by-side.png`

可核实的 Stage0 之后打标、边界首次运行、普通/长题字段整理、全链精修 usage 合计为 1,694,931 tokens；单窗口探测另计 6,980。图片节点重复文件覆盖和中断的长路径轮次使完整计费不可由本地证据重建，上述不是账单总量或费用估算。

含真实输出工作区的两轮完整回归均为 115 passed / 2 failed，失败落在 precleanup 和依赖它的 sealed-manifest 检查。首轮还存在新文件未分类；提交后未分类项归零，但清理扫描仍将 10 个本次运行输出目录列为可归档候选，与历史 post-archive “可归档根必须为零”的断言冲突。证据分别保存在 `foundation_before_commit/`、`foundation_with_live_artifacts/`。没有为了测试通过移动或删除真实样本证据。

最终从代码提交 `0817bbe` 创建干净验证工作树 `D:/Projects/TB-s04-check`，新建 `.venv` 并执行 `pip install -e .[dev]`，再运行相同 `run_final_chain_foundation_integration_gate.py`：**PASS，所有子命令退出码 0，聚合测试 117/117 通过**。产物复制到本地审计目录 `foundation_clean/`。本次属于 Windows/Python 3.12 的验证，没有声称执行远端 CI、Ubuntu 或 Java 业务回归。

机器证据入口为 `outputs/sets_teacher_trial_20260904_5799ab69/evidence.json`，记录关键交付件哈希、恢复文件来源、重放过程和验证结果。后续报告补记不改变 `0817bbe` 的已测试业务代码。

## 后端边界

本次验证的是原文到候选题包的 Python 加工主链。当前主链默认不执行数据库写入或 Runtime import；四链标准 CLI、结果契约、durable worker、checkpoint resume 与 Java ingestion boundary 的生产门禁仍然开放。真实题包通过内容审计后，仍需经正式 ingestion/审核边界接入 Java，不能用人工批准的 Release Seed 路径冒充任意原文自动入库。

另外，清理门禁应在未来识别并保护真实运行产物；本次干净检出的 PASS 不代表带运行历史工作区的清理检查已修复。
