package com.teachbase.server.identity.api;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * 一个精确的教师教学范围；学科和学段必须成对保存。
 */
public record TeachingScopeRequest(
        @NotBlank @Size(max = 80) String subject,
        @NotBlank @Size(max = 80) String stage,
        boolean primary) {
}
