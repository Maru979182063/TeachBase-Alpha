package com.teachbase.server.collection.application;

/** Optimistic-lock conflict carrying the version the client must reload. */
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
