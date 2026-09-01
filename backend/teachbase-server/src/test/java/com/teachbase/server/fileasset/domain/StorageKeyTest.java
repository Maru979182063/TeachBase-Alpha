package com.teachbase.server.fileasset.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;

class StorageKeyTest {

    @Test
    void acceptsPortableObjectKey() {
        assertThat(new StorageKey("workspaces/demo/source/doc.docx").value())
                .isEqualTo("workspaces/demo/source/doc.docx");
    }

    @Test
    void rejectsMachinePathsAndTraversal() {
        for (String invalid : new String[] {
                "C:\\Users\\demo\\doc.docx",
                "/var/data/doc.docx",
                "../doc.docx",
                "source/../doc.docx",
                "file:///tmp/doc.docx",
                "source\\doc.docx"
        }) {
            assertThatThrownBy(() -> new StorageKey(invalid))
                    .isInstanceOf(DomainValidationException.class)
                    .hasMessage("storage_key_must_be_portable_and_relative");
        }
    }
}
