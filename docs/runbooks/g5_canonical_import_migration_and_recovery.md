# G5 Canonical Import 迁移与恢复 Runbook

## 适用范围

本手册只处理 V010 canonical import ledger 和 package 的 validate、commit、resume、verify。它不负责 Risk 自动放行、S02 路由、搜索或解析链内部执行。

## 部署顺序

1. 备份数据库并记录当前 Flyway 版本。
2. 在隔离库执行 `npm run test:g5-v010-migration`，确认 V001→V010 与 V009→V010 均通过。
3. 部署理解 V010 的 Java writer。V010 是纯追加 migration，不删除或重写 V009、WP-01、Release Seed 表。
4. 保持 `TEACHBASE_CANONICAL_IMPORT_FAULT_INJECTION_ENABLED=false`。生产环境不得开启测试故障注入。
5. 上游先调用 validate，保存返回的 `importRequestId` 和 `packageHash`，再调用 commit。

## 正常恢复

1. 查询 `GET /api/v1/content-imports/{id}`，确认 workspace、package hash 和失败 operation。
2. 排除永久合同冲突，例如同 stable key 不同 payload、缺失 file version 或 workspace 越权。
3. 使用原 workspace、actor 和精确 package hash 调用 `POST /api/v1/content-imports/{id}/resume`。
4. 服务会验证已完成 target 仍存在，接管过期租约，并从第一个 failed/pending operation 继续。
5. 完成后调用 verify；`resultFingerprint` 不一致必须 fail closed。

## 并发与租约

每个 operation 在短事务开头锁定 request 行、核对 worker token 并续约。活跃租约拒绝第二个 worker；过期租约可接管。领域写入与 operation complete 同事务提交，因此失去 fencing token 的旧 worker 不能留下无 ledger 的写入。

## 永久冲突

以下错误不能靠重复 resume 修复：package key/hash 冲突、evidence key payload 冲突、frozen composition 冲突、artifact key payload 冲突、workspace 越权。应生成新的受控 package key，并保留失败 ledger 作为审计证据；不得直接改 ledger payload。

## 回滚

应用可回滚到不调用 G5 API 的 V009 writer，但数据库 migration 不向后删除。V010 只新增 nullable editor import identity、request/operation 表和保护 trigger，不影响旧 G4/WP-01 读写。已经成功创建的 immutable revision 不删除；恢复仍由理解 V010 的 writer 完成。

## 观测

重点监控 `status`、`completed_operation_count/operation_count`、`attempt_no`、`lease_expires_at`、失败 code、单 operation 时长和 package 总时长。`failed` 长期堆积、租约频繁过期或同 operation attempt 异常增长需要告警。
