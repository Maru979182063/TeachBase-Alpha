package com.teachbase.server.ingestion.application;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import java.util.function.Supplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/** 中文维护说明：在事务代理返回后记录结果和耗时；标签只用固定操作与状态，禁止写正文和凭据。 */
@Component
public class DeliveryObservation {
    private static final Logger LOG=LoggerFactory.getLogger(DeliveryObservation.class);
    private final MeterRegistry meters;
    public DeliveryObservation(MeterRegistry meters) { this.meters=meters; }
    public <T> T call(String operation,Supplier<T> task) {
        var sample=Timer.start(meters);String outcome="success";
        try { return task.get(); }
        catch(DeliveryException e) {outcome=e.status()==409?"conflict":e.status()<500?"rejected":"failure";throw e;}
        catch(RuntimeException e) {outcome="failure";throw e;}
        finally {
            sample.stop(Timer.builder("teachbase.delivery.duration").tag("operation",operation).tag("outcome",outcome).register(meters));
            meters.counter("teachbase.delivery.requests","operation",operation,"outcome",outcome).increment();
            LOG.info("delivery_operation operation={} outcome={}",operation,outcome);
        }
    }
}
