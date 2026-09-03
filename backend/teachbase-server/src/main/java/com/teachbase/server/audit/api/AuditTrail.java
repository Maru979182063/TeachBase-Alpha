package com.teachbase.server.audit.api;

/**
 * 中文维护说明：本文件属于审计模块的对外稳定合同层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Application port for recording an append-only business event in the caller's transaction.
 */
public interface AuditTrail {

    void record(AuditCommand command);
}
