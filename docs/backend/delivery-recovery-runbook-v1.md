# G3 对账、备份与恢复 v1

2026-09-08。仅允许受控本地运行；正式auth尚未完成，接收API、health和actuator不得直接暴露给不可信网络。启动时明确绑定 `SERVER_ADDRESS=127.0.0.1`。本阶段不部署生产数据库、不扩大真实灌装。

## 健康与观测

`GET /actuator/health/liveness` 表示进程存活。

`GET /api/v1/ingestion/deliveries/v1/health` 是healthSchemaVersion=1：ingestion在DB可读、没有非法已提交processing、storage目录可读写时为UP并返回200，否则DOWN/503。单独报告database、storage、storageUsableBytes、productionStableAuthorities=0。export为DISABLED、TOOLS_MISSING或TOOLS_PRESENT_UNVERIFIED；工具存在不代表真实渲染成功。此轻量接口不扫描全量文件，也不证明DB写权限、磁盘持久性或业务正确率。

`/actuator/metrics/teachbase.delivery.requests` 和 `teachbase.delivery.duration` 记录service调用结果/耗时，标签仅operation（preflight/import/receipt）和outcome（success/conflict/rejected/failure）。事务成功在代理COMMIT返回后统计；重放也计一次调用。HTTP200的eligible=false是成功返回预检结果；解析前的非法body/header不纳入这两个业务指标。日志记录成功请求/包/workspace和条数，逐题映射在receipt中查询；不记录密钥、题干全文或高基数指标标签。

## 全量一致性对账

工具：`node tools/delivery_storage_maintenance.mjs audit --storage-root STORAGE --out REPORT.json`。连接从环境变量 `TEACHBASE_MAINTENANCE_DATABASE_URL` 读取，使用外部安全注入，不写进命令行和Git。

对账枚举真实字节并计算SHA/size，检查登记路径边界；拒绝storage符号链接。引用来自题源、导出文件、G2包声明引用及题目资产证据。输出三个互斥文件分类：已引用、已登记未引用、未登记磁盘文件。孤立文件属于待处置证据，默认不会导致一致性失败；丢失、字节不符、引用未登记、receipt缺业务映射则失败。

同时核验完整delivery manifest摘要、包文件映射、请求状态/条数、receipt ID与两类hash、题目revision/review/source link关联，以及数据库保存的G0完整content摘要。历史规范域hash保持原合同，仅检查映射一致，不重写旧hash。此工具不作教学质量判断或自动清理。在线只读扫描可能遇到并发文件变化；准备用作恢复证据时必须停写。

## 一致性备份

1. 停止接收服务和所有可能写storage的进程，包括既有导出进程；等待在途事务结束。`--writers-stopped` 是运行方声明，不会自动停止外部进程。
2. 执行 `node tools/delivery_storage_maintenance.mjs backup --storage-root STORAGE --destination NEW_BACKUP_DIR --writers-stopped --out SUMMARY.json`。
3. 工具拒绝已有目标目录、storage内部备份路径和不一致源数据。在REPEATABLE READ事务内对teachbase_app表持有SHARE锁，导出PostgreSQL snapshot，pg_dump使用同一snapshot；复制全部storage后重新逐字节核验清单。
4. 保留 `database.dump`、`storage/`、`source-audit.json`、`manifest.json` 整体。manifest记录dump SHA/size、storage清单摘要、迁移版本/checksum、snapshot、完成receipt水位、备份时间与耗时。status必须为complete，且不能存在failure.json。

未登记文件也随备份保存，避免丢弃未完成接收可能需要的证据。独立文件系统没有与PG组成分布式事务，必须遵守受控不可变字节存储和停写前提。一次本地flush/恢复不证明断电或磁盘控制器故障耐受，也不构成自动异地灾备。

## 恢复到全新副本

1. 由运行方创建空PostgreSQL数据库，准备不存在的storage目标目录，并将维护连接环境变量指向该新库。目标与备份目录不得互相包含。
2. 执行 `node tools/delivery_storage_maintenance.mjs restore --backup-root BACKUP_DIR --storage-root NEW_STORAGE_DIR --out RESTORE_REPORT.json`。
3. 工具先核验备份完整标识、dump字节和storage清单；拒绝非空数据库、已有storage目录。pg_restore使用单事务、exit-on-error、no-owner/no-privileges，恢复后复制storage，再重新运行全部一致性对账、清单和迁移checksum比对。只有全部通过才返回passed。
4. 若失败，保留副本调查，禁止将其切换为在线库；工具不删除目标或自动覆盖重试。已存在的DB角色、网络权限和密钥不在数据库内容备份合同内，部署方需另行提供。
5. 启动指向新副本的同版本Java服务，查询历史 importRequestId 并重放同包，核对receipt逐字段一致；之后再次独立执行audit。成功后仍需运行方另行批准正式切换。

备份工具不提供在线增量备份、PITR、跨机自动切换、后台接收任务恢复。RPO为最近一次有效停写备份所能覆盖的范围；实际业务丢失窗口和生产RTO目标尚未约定。

## 可重复隔离演练

运行 `tools/run_g3_recovery_gate.mjs --source-data-root ORIGINAL_LOCAL_ROOT --out-dir NEW_OUTPUT`，会只读备份原52题库，在独立PG恢复副本中用实际G2 API再次接收52题，验证三类文件、缺失/损坏探测、健康依赖故障、指标、备份防误用、全新恢复和GET/retry原receipt。所有测试进程结束后清理自己的PG进程，原库做前后指纹比对。

容量工具 `tools/run_g3_capacity_gate.mjs` 使用同样参数。1千/1万/10万条合成元数据，1/5/10并发，每次50条、每档36个请求；记录p50/p95/p99、错误、数据库大小、索引、Java工作集峰值和Node RSS。SQL扩容只用于构造容量夹具，不能宣称100000题通过了G2接收。内容分布单一、本机热进程、有限请求数，其结论只适用于本地基线。
