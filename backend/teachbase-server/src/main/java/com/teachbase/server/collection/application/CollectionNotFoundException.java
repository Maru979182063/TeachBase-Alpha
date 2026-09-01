package com.teachbase.server.collection.application;

/** Raised when a collection is absent, archived, or outside the requested workspace. */
public class CollectionNotFoundException extends RuntimeException {

    public CollectionNotFoundException() {
        super("question_collection_not_found");
    }
}
