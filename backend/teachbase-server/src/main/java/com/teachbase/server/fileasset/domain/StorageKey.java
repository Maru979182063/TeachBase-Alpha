package com.teachbase.server.fileasset.domain;

import java.util.Arrays;
import java.util.regex.Pattern;

/** Portable relative object key; absolute and traversal paths are rejected. */
public record StorageKey(String value) {

    private static final Pattern URI_SCHEME = Pattern.compile("^[A-Za-z][A-Za-z0-9+.-]*:.*$");
    private static final Pattern WINDOWS_DRIVE = Pattern.compile("^[A-Za-z]:[\\\\/].*$");

    public StorageKey {
        value = value == null ? "" : value.trim();
        boolean parentSegment = Arrays.asList(value.split("/", -1)).contains("..");
        if (value.isBlank()
                || value.startsWith("/")
                || value.startsWith("\\")
                || value.contains("\\")
                || WINDOWS_DRIVE.matcher(value).matches()
                || URI_SCHEME.matcher(value).matches()
                || parentSegment) {
            throw new DomainValidationException("storage_key_must_be_portable_and_relative");
        }
    }
}
