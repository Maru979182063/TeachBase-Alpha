package com.teachbase.server.fileasset.domain;

/** Sanitized display filename that never controls a filesystem path. */
public record OriginalFilename(String value) {

    public OriginalFilename {
        value = value == null ? "" : value.trim();
        if (value.isBlank() || value.contains("/") || value.contains("\\")) {
            throw new DomainValidationException("original_filename_must_not_contain_path_segments");
        }
    }
}
