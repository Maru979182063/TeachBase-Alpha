package com.teachbase.server.fileasset.domain;

import java.util.Locale;
import java.util.regex.Pattern;

/** Lowercase 64-character SHA-256 value object. */
public record Sha256(String value) {

    private static final Pattern FORMAT = Pattern.compile("^[0-9a-f]{64}$");

    public Sha256 {
        value = value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
        if (!FORMAT.matcher(value).matches()) {
            throw new DomainValidationException("sha256_must_be_64_lowercase_hex_characters");
        }
    }
}
