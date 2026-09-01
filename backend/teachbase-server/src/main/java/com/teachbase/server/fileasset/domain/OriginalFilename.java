package com.teachbase.server.fileasset.domain;

/**
 * 中文维护说明：本文件属于文件资产模块的领域值对象层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Sanitized display filename that never controls a filesystem path.
 */
public record OriginalFilename(String value) {

    public OriginalFilename {
        value = value == null ? "" : value.trim();
        if (value.isBlank() || value.contains("/") || value.contains("\\")) {
            throw new DomainValidationException("original_filename_must_not_contain_path_segments");
        }
    }
}
