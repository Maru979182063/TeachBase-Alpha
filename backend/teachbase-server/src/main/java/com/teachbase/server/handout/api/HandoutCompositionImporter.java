package com.teachbase.server.handout.api;

import java.util.UUID;

/** 中文维护说明：统一导入核心通过此端口提交已冻结 editor revision 的完整 composition。 */
public interface HandoutCompositionImporter {

    HandoutCompositionResponse importComposition(
            UUID editorDocumentId, UUID editorRevisionId, CreateHandoutCompositionRequest request);
}
