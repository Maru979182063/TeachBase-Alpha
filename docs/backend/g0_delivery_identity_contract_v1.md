# G0 交付与身份合同 v1

状态：第一阶段交付；本合同不接通灌装 HTTP，不创建接收回执表，不修改四链算法。

正式 schema：[backend_candidate_delivery_v1.schema.json](../../schemas/backend_candidate_delivery_v1.schema.json)。JSON Schema Draft 2020-12；引用关系、键唯一性、注册来源和哈希等跨字段规则由 [纯合同参考实现](../../tools/candidate_delivery_contract.py) 验证。仅使用 schema 验证器通过不足以宣告可入库。

## 三个键分别负责什么

| 字段 | 职责 / 作用域 | 不承担的职责 |
| --- | --- | --- |
| importRequestId | 调用方生成的随机 UUID；workspace 内唯一的本次提交/重试键，同一次重试复用 | 不识别同一道题，不由内容或模型 runId 生成 |
| stableQuestionKey | 已登记来源提供的 opaque 持久 ID；后端以 workspace、sourceSystem、已登记 stableKeyNamespace 共同作用域匹配 | 不从题号、序号、文本、模型相似度、正则或启发式推导 |
| contentHash | `tb-content-v1` 下的规范内容摘要；命中题目后用于判断是否需新修订 | 不跨题合并，不充当稳定身份或请求 ID |

包摘要 requestDigest 则绑定 importRequestId 所提交的具体包内容。G0 只计算摘要并测试相等/不同；持久化绑定和相应 HTTP 409 是 G2 验收项，本轮不宣称已实现。

## 身份模式

`one_shot_candidate`：stableQuestionKey 必须为 null，candidateId 必须由交付方随机分配并保留在本次交付包中；后端身份作用域为 `(workspaceId, sourceSystem, one_shot_candidate, packageId, candidateId)`。itemKey、题号、数组顺序均不参与身份。packageId 是交付实例 ID，同一包重试复用；新一轮加工创建新包，即使正文一致也不承诺命中旧题。G2 需要落实同一 packageId 的不可变交付内容校验；G0 不具备跨请求历史状态。

`registered_stable`：要求 stableQuestionKey、identityContractId、identityContractVersion、anchorEvidence。后端注册表指定稳定键命名空间、允许的 anchor 字段和是否要求 documentStableKey。未知来源或合同版本拒绝，不接受包内自封“稳定”。注册版本改变只有在后端明确登记同一键命名空间时才保持身份；后端不生成稳定键。

生产注册表 [identity-authorities.v1.json](contracts/identity-authorities.v1.json) 目前为空。四条加工链尚无已确认、已回归验证的稳定锚点合同，所以当前真实产物只能采用 one-shot candidate identity。测试用注册表位于 tests/fixtures，明确不是生产注册。

注册表是受信的后端配置；启用来源前还需人工确认该来源的持久 ID 语义及真实重复加工证据。结构检查不能证明持久 ID 真实存在，也不能证明不同 anchorEvidence 对应同一题；跨包键与锚点映射冲突、来源认证属于后续接收/认证实现，不能用本轮夹具验证代替。

## 交付字段与原始证据

顶层包含协议版本、请求/包 UUID、workspace、sourceSystem、pipeline run/profile、文件清单、原文清单、questions。最多 100 题。未知字段拒绝，后续扩展必须显式演进 schema。

每题包含包内 itemKey、互斥 identity、sourceDocumentKey、sourceEvidence、content、可空 contentHash、classificationSuggestions。itemKey 仅用于逐项回执定位，允许显示序号但绝不能用于身份匹配。sourceBlockRefs/pageNumbers 只是原始证据；页码缺失用空数组表示，不推断补齐。

content 包含独立 contentSchemaVersion、标题、材料、题干、选项、子问正文数组、答案、解析、教学说明和媒体引用。子问保留已有原文编号，不增加教学结构推断。原始复杂题包、坐标及风险/模型留证可作为完整文件列入 evidenceFileKeys；本阶段不约定尚未确认的 bbox 教学分区或跨链内部 JSON。

classificationSuggestions 是来源建议，不是有效标签或审核决定；空字段明确为 null，tags 可为空。来源通过文件 SHA-256 与相对路径交付；当前工具仅检查清单关联和路径形式，不读取资产字节，不执行真实入库预检。实际字节核验在 G2 完成。

题目 Markdown 的媒体引用与 content.media 映射由后续内容适配器验证；本轮验证媒体哈希/类型能在清单中解析，不声称已完成四链 Markdown 内引用的全面核验。

## 哈希合同 tb-json-v1 / tb-content-v1

tb-json-v1：UTF-8，无 BOM；对象键按 Unicode 码点排序；数组保留原顺序；无额外空白；按 JSON 转义引号、反斜杠和控制字符（短转义适用时用短转义，否则小写十六进制）；非 ASCII 不转义。禁止重复 JSON 成员、非有限数、浮点数、孤立 surrogate 和超出 ±(2^53−1) 的整数。字符串不 trim、不做 Unicode/换行/LaTeX 归一化。本算法是项目合同，不宣称等同 RFC 8785。

contentHash = SHA256(tb-json-v1({hashContract: "tb-content-v1", content: 每题content}))。分类建议、来源、runId/profile、题目身份、itemKey 不参与；媒体引用、选项和子问参与。提供非 null contentHash 时必须与重算结果相同。

requestDigest = SHA256(tb-json-v1({hashContract: "tb-delivery-v1", manifest: 去掉importRequestId后的完整包}))。改请求 ID 不改变摘要；改 pipeline、来源、建议或正文会改变摘要。同 packageId 的包内容只能重放不能改写，G2 需要持久化验证该不变量。

这是新交付合同的哈希空间。现有 Java QuestionService 的 contentHash 含旧业务字段，历史 revision 不重新计算、不回填覆盖。G2 适配时应保存交付摘要与旧/新领域修订摘要的明确映射，并按 content schema 版本演进，不假定两者天然相同。

## 兼容及实测边界

现有 `/api/v1/ingestion/candidate-batches` 和 DOCX 适配器保持原有合同；它们没有自动获得 stableQuestionKey、requestDigest 或持久化回执能力。本阶段不把旧的整包哈希来源键重命名成稳定键，也不回写现有 52 题身份。

运行：`python tools/candidate_delivery_contract.py tests/fixtures/candidate_delivery/one-shot.json`。

测试：`python -m pytest tests/test_candidate_delivery_contract.py -q --junitxml=artifacts/ci/g0-g1/g0-junit.xml`。身份矩阵验证纯合同的键/摘要行为和拒绝条件；数据库跨请求重放、崩溃恢复、revision 写入归并属于 G2 的后续集成测试，不能将其报为本轮已通过。

## 仍需加工链确认的 stable anchor

1. 来源系统 namespace 和 identityContractId/version 的维护者。
2. 真正持久的题目记录 ID 或持久源节点 ID，是否在重跑、改模型、改 prompt、重新分页、局部增删后保持不变。
3. 原文的 documentStableKey 是否独立于文件字节版本；若只能提供文件哈希，不能承诺换文档版本后的身份连续。
4. anchorEvidence 的精确字段、键作用域、唯一性和生成方；不能用本轮题号/序号/bbox 临时组合顶替。
5. 拆题、合题、删题和来源重建后的 ID 生命周期；哪些情况明确创建新身份。
6. 至少两轮真实产物的持久键对照，以及重复键/一对多冲突样例。

这些字段未确认前，生产稳定来源注册表保持为空；one-shot 候选可以表达现状，但跨轮自动修订归并仍未验收。
