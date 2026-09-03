package com.teachbase.server.exporting.application;

/**
 * 中文维护说明：本文件属于稳定导出与渲染队列模块的业务规则与事务编排层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Deterministic audience-specific Markdown produced from a frozen editor snapshot.
 */
public record RenderSourceDocument(
        int schemaVersion,
        String adapterVersion,
        String audience,
        String markdown) {
}
