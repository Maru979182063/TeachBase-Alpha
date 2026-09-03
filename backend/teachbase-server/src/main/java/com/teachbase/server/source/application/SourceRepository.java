package com.teachbase.server.source.application;

import com.teachbase.server.source.api.RegisterSourceDocumentCommand;
import com.teachbase.server.source.api.RegisterSourceRegionCommand;
import com.teachbase.server.source.api.SourceRegistration;

/**
 * 中文维护说明：本文件属于题源证据模块的业务规则与事务编排层，定义持久化端口，调用方只依赖业务所需的最小能力。
 *
 * 英文术语对照：Persistence port for workspace-scoped, idempotent source evidence.
 */
public interface SourceRepository {

    SourceRegistration registerDocument(RegisterSourceDocumentCommand command);

    SourceRegistration registerRegion(RegisterSourceRegionCommand command);
}
