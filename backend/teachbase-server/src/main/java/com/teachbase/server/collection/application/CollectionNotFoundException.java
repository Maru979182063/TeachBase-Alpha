package com.teachbase.server.collection.application;

/**
 * 中文维护说明：本文件属于题篮与快照模块的业务规则与事务编排层，表达可识别的业务失败，错误码和重试语义属于对外合同。
 *
 * 英文术语对照：Raised when a collection is absent, archived, or outside the requested workspace.
 */
public class CollectionNotFoundException extends RuntimeException {

    public CollectionNotFoundException() {
        super("question_collection_not_found");
    }
}
