package com.teachbase.server.fileasset.api;

/** Registers a generated artifact after its bytes and SHA-256 have been finalized. */
public interface GeneratedFileRegistrar {

    GeneratedFileRegistration registerGeneratedFile(GeneratedFileCommand command);
}
