package com.teachbase.server.handout.application;

/** 中文维护说明：讲义 composition 结构、引用或幂等冲突的稳定业务异常。 */
public class HandoutValidationException extends IllegalArgumentException {
    public HandoutValidationException(String message) {
        super(message);
    }
}
