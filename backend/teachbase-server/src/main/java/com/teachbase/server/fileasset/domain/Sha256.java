package com.teachbase.server.fileasset.domain;

import java.util.Locale;
import java.util.regex.Pattern;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Lowercase 64-character SHA-256 value object.
 */
public record Sha256(String value) {

    private static final Pattern FORMAT = Pattern.compile("^[0-9a-f]{64}$");

    public Sha256 {
        value = value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
        if (!FORMAT.matcher(value).matches()) {
            throw new DomainValidationException("sha256_must_be_64_lowercase_hex_characters");
        }
    }
}
