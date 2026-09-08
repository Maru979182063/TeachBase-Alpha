# 第二阶段 G2/G3 验收报告

日期：2026-09-08。结论：本阶段实现与隔离验证已完成，提交用户验收，停止在第二阶段门禁。没有启动G4/G5，没有迁移、批量灌装或批准原题库。

实现位于独立worktree `D:/Projects/TeachBase-Alpha-backend-g2-g3-20260908`，分支 `codex/backend-g2-g3-20260908`；基线为第一阶段验收提交 `db445d6`。G2、G3、最终验收报告分别提交。V001—V009逐文件与基线核对未变，仅追加V010；四条加工链内部算法没有修改。

实施提交：G2 `38deaae`；G3 `fbed3a7`。最终报告与既有回归证据另一个提交，整条分支供审阅，不合并主线。

## 1. G2 API / schema 最终定义

详细合同：[candidate-delivery API v1](../backend/contracts/candidate-delivery-api-v1.md)。

| 项目 | 最终定义 |
|---|---|
| 输入 | 原G0 [candidate-delivery v1 schema](../../schemas/backend_candidate_delivery_v1.schema.json)，保持不变 |
| 预检 | POST `/api/v1/ingestion/deliveries/v1/preflight`，只读，200返回 [preflight v1](../../schemas/backend_delivery_preflight_v1.schema.json) |
| 提交 | POST `/api/v1/ingestion/deliveries/v1/imports`，首次201，重放200，返回 [receipt v1](../../schemas/backend_delivery_receipt_v1.schema.json) |
| 恢复响应 | GET `/api/v1/ingestion/deliveries/v1/requests/{importRequestId}?workspaceId=UUID`，成功200，未提交/不存在404 |
| 操作者 | 必需X-Actor-Id，校验workspace有效成员；仍是本地信任模型，不是正式auth |
| 边界 | 1—100题、JSON body≤16MiB、单文件≤64MiB、声明总文件≤512MiB，同步数据库事务timeout120s |
| 文件入口 | 已登记同workspace资产，或受控storage/inbox/workspace/package/相对路径；本期无公网multipart上传 |
| 错误 | 400输入格式、403成员范围、409请求/包冲突、413body限制、422合同或提交条件不满足、500事务/内部故障 |

实际HTTP预检与receipt已按最终JSON Schema验证。Java与G0 Python对中文、增补Unicode、控制字符及声明hash黄金向量的摘要一致。拒绝重复JSON成员、尾随第二个JSON和空输入。

旧规范域仍要求subject和questionType明确非空，stem非空；title等有既有长度限制，PostgreSQL JSON不支持U+0000。以准入错误报告，不改G0结构合同，也不补造教学语义。缺知识标签、难度、页码可以带warning保存待审核。taxonomy建议只验证可解析并保存证据，不写成已确认标签。

## 2. importRequest 生命周期与状态机

`absent → processing（仅未提交事务内） → succeeded`。任意失败整批回滚回absent；没有后台任务、failed持久状态或可提交的processing。本阶段记录成功接收事实，故障诊断由HTTP/日志提供。

| 情形 | 行为 |
|---|---|
| 同workspace、同requestId、同deliveryDigest | 返回原receipt，逐字段不变，不增加业务行 |
| 同requestId、不同包声明 | 409；不覆盖原receipt |
| 新requestId、同一不可变package | 新建请求receipt并复用原业务映射；不重开审核 |
| 同packageId、不同声明 | 409；package不可变 |
| 新packageId、相同candidateId/相同内容 | 新建候选，不作跨包归并 |
| 客户端丢失成功响应 | GET或同ID同包重试恢复原receipt |
| GET返回404 | 表示尚无已提交结果，不能据此断言请求从未执行；可同ID同包重试 |

importRequestId只管一次请求；packageId管交付包；contentHash管G0内容版本。服务器依据G0 `tb-delivery-v1` 自行计算deliveryDigest，排除requestId，保留其他声明与数组顺序。contentHash与旧domainContentHash同时保留，未覆盖任何历史hash。

**生产stable-source registry仍为空**。one-shot不会自动升级。可靠稳定锚点声明和两轮真实加工产物未齐备前，registered_stable请求拒收。

## 3. receipt表及事务边界

[V010迁移](../../backend/teachbase-server/src/main/resources/db/migration/V010__candidate_delivery_receipts.sql)新增四表：

| 表 | 职责 |
|---|---|
| delivery_package | workspace+packageId，完整不可变manifest与服务端digest |
| delivery_request | workspace+requestId，包关联、状态、接收/完成时间、成功receipt JSON |
| delivery_request_item | request+itemKey，question/revision/review/source_region及两类hash |
| delivery_package_file | package+fileKey，受控文件登记、SHA、引用标记 |

请求锁→包锁→提交时重新检查成员、声明、现存包、taxonomy引用、文件字节→登记文件→来源/区域→题目与revision→来源关联→待审核case→item映射→最终字节检查→成功receipt→同一PG事务COMMIT。

主键、外键和延迟约束共同保证最终receipt的状态、数量、逐项真实业务映射。成功request、包、item和文件映射禁止更新/删除；item新增也触发延迟完整性验证。没有将一次早先的preflight当成预留身份或事务成功证明。

文件系统与PG没有分布式事务。文件先核验、复制、flush，再随事务登记；事务失败可留下未登记磁盘文件。G3完整保存和分类这些文件，不自动删除。目录须由受控服务管理；本次验证不包含断电、磁盘控制器故障或恶意管理员直接改数据。

## 4. 幂等、并发、响应丢失与故障实测

完整证据：[G2实际接收门禁](evidence/g2-g3-20260908/g2-delivery.json)。

| 实测场景 | 结果 |
|---|---|
| 52题真实内容适配包preflight | eligible=true；156项缺标签/页码/难度warning；业务计数不变 |
| 52题实际API提交 | 201；52个完整question/revision/review/source映射；副本题目52→104 |
| 相同请求重放与GET | 原receipt完全一致，业务计数不增 |
| 相同ID不同内容 | 409；伪造deliveryDigest字段被schema拒绝 |
| 6个并发相同请求 | 1个201、5个200，只新增1题和1条请求 |
| 2个并发同ID不同内容 | 1个201、1个409 |
| 相同包新request | 复用映射；在测试副本已结束的审核case不重开 |
| 不同包相同candidateId与内容 | questionId不同，contentHash相同 |
| 成功后本地代理故意断开响应 | 客户端报连接失败，但GET及重试均恢复原成功receipt |
| 成功receipt更新前触发数据库异常 | HTTP500；题目、来源、审核、request全部回滚；同请求随后可成功 |
| COMMIT前阻塞并强制终止Java | 无可见成功receipt或新增业务；重启后同请求201 |
| 直接SQL提交processing/无item的伪成功receipt | 延迟约束23514拒绝 |
| 超过100题/单文件限制 | 拒绝，无部分写入 |

本次“真实包”具体指：从原52题已有内容、规范revision和35个实际来源/资产文件制作G0 one-shot适配包，保存既有来源证据文件，并经新的G2 HTTP入口接收。没有重新调用四条加工链，也不是“四链新出口均已对接通过”。candidateId采用明确新UUID，既有revisionId只作item定位，未猜测稳定身份。

## 5. preflight与commit一致性实测

预检通过后改变inbox文件字节，commit重新计算SHA并返回422；题目、revision、review、request计数完全不变，GET404。第二题非法时整包拒绝，第一题不残留。非成员GET403；未登记stable来源无法通过准入。

同ID冲突与包冲突在持有事务锁后重新仲裁。已成功请求重放先取原receipt，不依赖临时inbox仍在，符合响应丢失恢复要求。不同request尝试再次引用同包仍做当前准入检查，不能借旧preflight绕过当前条件。

G2不判定题干准确性、题源单拆质量、图片教学归属或标签教学正确性；这些仍由加工链证据与审核承担。

## 6. DB/storage对账和恢复

工具及操作步骤：[G3运行手册](../backend/delivery-recovery-runbook-v1.md)。完整实测：[G3恢复证据](evidence/g2-g3-20260908/g3-recovery.json)。

实际G2接收52题后再备份，副本有104题/104revision/104review、1个成功request、52个receipt items。已引用文件35个；特设已登记未引用文件1个；未登记磁盘文件2个（inbox副本和孤立夹具）。全部38个磁盘文件约5,114,682字节，一并保留。缺失或损坏已引用文件可准确检测，没有自动修复/清理。

停写后持有规范表SHARE锁，以同一个导出snapshot完成pg_dump与存储清单核验；备份记录迁移checksum、dump SHA、存储清单摘要、时间和成功receipt水位。恢复入口先验证备份，拒绝损坏包、非空数据库和已有storage目录，恢复到全新数据库与目录后重新核验全部关系和字节。

| 最终演练测量 | 耗时 |
|---|---:|
| 52题实际同步import（单次观察） | 1,950 ms |
| 停写一致性备份 | 502 ms |
| 备份校验、DB/storage恢复 | 757 ms |
| 恢复工具内全量一致性核验 | 93 ms |
| 独立再次执行全量核验 | 132 ms |
| 恢复副本Java启动至health通过 | 6,347 ms |

恢复结果：迁移与checksum、包digest、存储清单、文件分类、题目/来源/审核关联、receipt两类hash均一致；GET与同ID重试逐字段恢复原receipt。上述恢复步骤合计约7.33秒，不含人工准备和创建空库，不作为生产RTO；正式RPO/RTO、异地备份与断电场景尚未约定。

健康探测实测：storage目录不可用时接收503，DB仍UP、liveness仍200；接收表不可用时接收503、liveness仍200；依赖恢复后回到200。关闭导出独立显示DISABLED。已验证请求计数指标只有固定操作/结果标签，无题目或请求ID高基数标签。

## 7. 容量基线

完整分位数、吞吐、数据库体积、索引和进程采样：[容量证据](evidence/g2-g3-20260908/capacity.json)。Windows 11本机，i7-14650HX、24逻辑CPU、约15.64GiB内存。独立副本；每档另有原52题。合成内容单模板，以独立UUID扩充元数据；没有批量灌装真实题目。

每格36个请求，正向全命中/反向无命中查询交替，返回每页50条；本机热进程，nearest-rank分位数。

| 合成题数 | 1并发p95 | 5并发p95 | 10并发p95 | 非预期错误 |
|---:|---:|---:|---:|---:|
| 1,000 | 33 ms | 28 ms | 17 ms | 0 |
| 10,000 | 50 ms | 51 ms | 58 ms | 0 |
| 100,000 | 200 ms | 466 ms | 543 ms | 0 |

1万题、5并发、50条/页的本地门槛p95≤1秒、非预期错误0：本次达到。10万题数据库约246.85MB，10并发p99为552ms；Java进程测得峰值工作集399,663,104字节，Node采样RSS最高77,860,864字节。SQL元数据扩充耗时约1.03s/11.14s/114.08s，不能换算为G2灌装吞吐。

单模板分布、36次/格、同机网络和热缓存限制了结果；未做持续soak、跨机并发、全量多样真实题库压力，也没有完整PG/OS内存峰值采样。容量基线不证明生产可用率、教学质量或项目完成百分比。真实图片/公式导出另由下述回归验证；该回归不构成批量导出吞吐或峰值资源承诺。

## 8. 原52题与既有governance回归影响

原库最终[只读核验](evidence/g2-g3-20260908/original-state.json)：52题、52待审核、0批准、52review、0有效taxonomy绑定、35登记文件字节全部一致，仍停留V008。原库未应用V009/V010；原本关闭的PG只为只读备份临时启动，收尾恢复关闭。测试前后业务指纹一致。

| 回归项 | 实际结果与证据 |
|---|---|
| G0合同 | Python32项与Java跨语言黄金向量通过，生产registry为空 |
| Java/模块边界 | 21项通过，无跳过；[构建与历史迁移核验](evidence/g2-g3-20260908/contract-and-build.json) |
| G1主标签 | [10项回归](evidence/g2-g3-20260908/g1-regression.json)通过；冲突扫描0，迁移遇冲突中止；并发primary一成功一409；跨版本历史保留 |
| 既有governance | [回归证据](evidence/g2-g3-20260908/governance.json)通过：禁止直接批准导入、内容hash守卫、并发决定一成功一冲突、taxonomy不可变、修订绑定和审计 |
| 真实52题业务 | [22项回归](evidence/g2-g3-20260908/real52-regression.json)通过：待审核搜索/放置限制、选择篮并发与checkpoint、引用、修订指针、冻结快照、选项/子问、师生答案隔离 |
| 真实导出 | 教师/学生各DOCX和PDF成功；教师18图、学生9图均保留；DOCX分别885/343个原生公式；PDF分别20/6页 |

所有用于验证“批准后引用/导出”和审核终态行为的决定仅在隔离测试副本，原题库没有任何批准。测试数量只用于说明覆盖证据，不能折算项目完成度。既有网页公式渲染问题未在本轮修复。

## 9. 尚未关闭的问题与停门

| 问题 | 当前边界 / 后续必要证据 |
|---|---|
| stable anchor | 缺两轮真实加工产物和加工方稳定性声明；需明确source authority、documentStableKey、原始记录/块持久ID、anchor版本、边界变更/拆合题规则；不得以题号、顺序、正则、相似度或内容hash猜测 |
| auth与动作权限 | X-Actor-Id仍为客户端声明，成员检查不能证明真实身份；服务账号、可信入口、角色/动作权限和私有资源策略待独立实施，当前仅限受控本地 |
| 四链真实样本 | 已有doc_math真实52题适配包通过G2；其余链及新版本出口缺完整真实交付样本和重跑对照。四链内部算法完全未改 |
| 内容质量/标签 | 缺项warning保留；标签建议不等于确认标签；题源独立裁剪、语义归属和公式网页呈现仍须各自验收 |
| 运行生产目标 | 正式容量、长稳压力、多人网络场景、PG/OS完整资源峰值、批量导出压力、异地备份及RPO/RTO未关闭 |

本阶段可供验收的能力是：**受控本地、版本化、同步有界的待审核候选接收，以及成功回执查询、重试和可重复DB/storage恢复**。本报告不批准生产stable source、真实大规模灌装或真实题目。

**第二阶段已停门，等待用户验收。G4审核治理、G5搜索投影没有启动。**
