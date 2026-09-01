package com.teachbase.server.collection.application;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，表达可识别的业务失败，错误码和重试语义属于对外合同。
 *
 * 英文术语对照：Optimistic-lock conflict carrying the version the client must reload.
 */
public class CollectionVersionConflictException extends RuntimeException {

    private final long currentDraftVersion;

    public CollectionVersionConflictException(long currentDraftVersion) {
        super("question_collection_version_conflict");
        this.currentDraftVersion = currentDraftVersion;
    }

    public long currentDraftVersion() {
        return currentDraftVersion;
    }
}
