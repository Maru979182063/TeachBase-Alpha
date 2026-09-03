package com.teachbase.server.identity.api;

/**
 * 返回给工作台的规范化教学范围。
 */
public record TeachingScopeResponse(String subject, String stage, boolean primary) {
}
