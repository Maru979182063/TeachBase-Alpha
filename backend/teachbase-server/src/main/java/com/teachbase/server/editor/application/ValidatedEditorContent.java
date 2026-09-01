package com.teachbase.server.editor.application;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * 中文维护说明：本文件属于在线编辑文档模块的业务规则与事务编排层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Canonical JSON strings and deterministic hash produced by editor validation.
 */
public record ValidatedEditorContent(
        int schemaVersion,
        JsonNode masterDoc,
        JsonNode versionOverrides,
        String masterDocJson,
        String versionOverridesJson,
        String contentHash) {
}
