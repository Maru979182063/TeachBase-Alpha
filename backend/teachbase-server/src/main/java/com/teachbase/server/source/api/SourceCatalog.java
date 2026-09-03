package com.teachbase.server.source.api;

/**
 * 中文维护说明：本文件属于题源证据模块的对外稳定合同层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Named module port for durable source evidence registration.
 */
public interface SourceCatalog {

    SourceRegistration registerDocument(RegisterSourceDocumentCommand command);

    SourceRegistration registerRegion(RegisterSourceRegionCommand command);
}
