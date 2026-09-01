package com.teachbase.server.exporting.application;

/** Non-retryable snapshot-to-render-source contract failure. */
public class RenderSourceException extends RuntimeException {

    public RenderSourceException(String code) {
        super(code);
    }
}
