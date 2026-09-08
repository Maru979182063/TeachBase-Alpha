# G2 candidate delivery API v1

2026-09-08。输入保持已验收的 `schemas/backend_candidate_delivery_v1.schema.json`，无新增教学语义。响应分别由 `backend_delivery_preflight_v1.schema.json` 和 `backend_delivery_receipt_v1.schema.json` 定义。生产 identity-authorities registry 继续为空。

## API

统一前缀 `/api/v1/ingestion/deliveries/v1`，JSON，必需 `X-Actor-Id: UUID`。workspace 来自 manifest 或查询参数。仅校验有效 workspace 成员；此 header 是现有本地信任模型，不能当成可对外开放的身份认证。

| 方法与路径 | 输入 | 成功响应 |
|---|---|---|
| POST `/preflight` | 完整 G0 manifest | 200，preflight v1；eligible=false 时 issues 给出字段路径 |
| POST `/imports` | 同一完整 manifest | 首次提交201；同请求重放200；body为持久化 receipt v1 |
| GET `/requests/{importRequestId}?workspaceId=UUID` | UUID，actor header | 200，原 receipt；不存在或尚未提交404 |

400=JSON/UUID/header非法；403=非有效成员；409=`delivery_request_conflict` 或 `delivery_package_conflict`；413=body过大；422=合同/存储/规范域准入失败；500=事务或内部故障。ProblemDetail.detail 是稳定错误代码。客户端可在422后重新 preflight 获取定位；preflight 不签发可绕过校验的 token。

## 有界准入与文件交付

每包1—100题；body≤16MiB；单文件≤64MiB；声明文件总量≤512MiB；同步事务timeout120s（数据库/JDBC事务限制，不承诺所有网络与文件I/O均会在120s强制中断）。无后台worker、异步批任务或逐题续跑。

文件先放到受控的 `storage/inbox/<workspace UUID>/<package UUID>/<manifest.path>`，或复用同 workspace 已登记且 SHA/size/mediaType 一致的文件。API接收manifest；本阶段不提供公网multipart上传。预检核验实际文件大小、SHA和路径边界。提交复制到不可变内容寻址文件、flush字节、再登记数据库。文件系统与PostgreSQL没有分布式事务：失败允许留下未登记文件，G3只报告，禁止自动删除。运行方须独占管理该目录，不能有绕过服务的写入者。

旧规范域要求 subject、questionType 显式非空且≤80，stage/grade≤80、title≤512（Java字符串长度）；stem非空；PostgreSQL JSON不接收U+0000。本阶段用准入错误表达，不改G0交付schema，不编造缺失分类。缺知识标签、来源页码、难度为warning，仍可待审核。taxonomy建议只验证节点可解析，完整保存建议证据，不直接建立有效主标签。G1原有revision+taxonomy version约束继续生效。

## 身份、摘要与状态机

`workspace + importRequestId` 是请求幂等身份；`workspace + packageId` 是不可变交付包身份。服务端按G0 `tb-delivery-v1` 自行计算SHA256，排除 importRequestId，保留数组顺序与所有其他声明。客户端不能提交可信digest；未知字段会被拒绝。contentHash为G0内容摘要；domainContentHash保留既有规范域摘要，两者职责不混用。

状态转移：`absent → processing（仅事务内） → succeeded`。任一步失败均rollback回absent；不会持久化failed或processing。成功请求禁止更新/删除，历史receipt不随后续审核变动。404不能区分从未提交、已失败、尚在执行；未知提交结果的客户端应查询或同ID同包重试。

同ID同包先锁定再返回原receipt，不重算时间、不重开审核、不要求inbox还在；同ID异包409。相同package的新request产生自己的receipt并复用原业务映射，不是跨包题目归并；同package异内容409。新package即便candidateId和内容都相同也新建候选。registered_stable一律拒收：没有两轮真实加工证据及稳定锚点声明，不注册、不提升。

## 持久化与事务边界

仅追加V010。四表：delivery_package保存不可变manifest/digest；delivery_request保存状态/receipt；delivery_request_item保存题目、revision、review、source_region和两类hash映射；delivery_package_file保存已核验文件登记与引用关系。

请求锁→包锁→重新校验成员、合同、现存包摘要、分类建议和实际文件→文件登记→题源/区域→question/revision→source link→pending review case→逐项映射→最终文件复核→写成功receipt→同一PostgreSQL事务COMMIT。冲突靠锁、唯一键与事务共同仲裁，不信任先前preflight。延迟约束在提交时校验最终状态、条目数量和真实业务映射，阻止processing或空业务的成功receipt提交；条目INSERT也触发完整性校验。

客户端断线不会撤销已成功COMMIT。GET返回原始JSON结果。存储故障、DB触发器异常、COMMIT前Java进程终止均不允许出现已提交成功receipt而本次业务行缺失。历史数据被拥有直接SQL权限者另行破坏属于运维审计和权限边界，G3会重新核验图关系与实际字节。

G4审核治理扩展和G5搜索投影未在此入口实施。
