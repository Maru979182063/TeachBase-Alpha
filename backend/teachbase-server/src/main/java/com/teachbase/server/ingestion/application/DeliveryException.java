package com.teachbase.server.ingestion.application;

/** 中文维护说明：接收错误使用明确 HTTP 状态和结构码，不包含题目正文或文件绝对路径。 */
public class DeliveryException extends RuntimeException {
    private final int status;
    public DeliveryException(int status, String code) { super(code); this.status = status; }
    public int status() { return status; }
}
