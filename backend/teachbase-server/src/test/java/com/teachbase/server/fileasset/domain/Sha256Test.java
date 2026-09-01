package com.teachbase.server.fileasset.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;

class Sha256Test {

    @Test
    void normalizesUppercaseHex() {
        String uppercase = "A".repeat(64);
        assertThat(new Sha256(uppercase).value()).isEqualTo("a".repeat(64));
    }

    @Test
    void rejectsMalformedHash() {
        assertThatThrownBy(() -> new Sha256("not-a-hash"))
                .isInstanceOf(DomainValidationException.class);
    }
}
