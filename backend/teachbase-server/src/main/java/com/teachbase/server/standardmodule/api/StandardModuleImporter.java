package com.teachbase.server.standardmodule.api;

import java.util.UUID;

/** 中文维护说明：统一导入核心只能通过此公开端口创建模块修订及其来源/文件关系。 */
public interface StandardModuleImporter {

    StandardModuleResponse importModule(CreateStandardModuleRequest request);

    StandardModuleLinkResponse importSource(UUID revisionId, LinkStandardModuleSourceRequest request);

    StandardModuleLinkResponse importFile(UUID revisionId, LinkStandardModuleFileRequest request);
}
