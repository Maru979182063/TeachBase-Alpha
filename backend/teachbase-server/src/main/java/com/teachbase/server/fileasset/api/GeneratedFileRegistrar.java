package com.teachbase.server.fileasset.api;

/**
 * 中文维护说明：本文件属于文件资产模块的对外稳定合同层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Registers a generated artifact after its bytes and SHA-256 have been finalized.
 */
public interface GeneratedFileRegistrar {

    GeneratedFileRegistration registerGeneratedFile(GeneratedFileCommand command);
}
