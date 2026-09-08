package com.teachbase.server.ingestion.api;

import com.teachbase.server.ingestion.infrastructure.DeliveryOperations;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** 中文维护说明：独立运行健康端点，接收依赖故障返回503；关闭导出不会让接收探测误报故障。 */
@RestController
class DeliveryOperationsController {
    private final DeliveryOperations operations;
    DeliveryOperationsController(DeliveryOperations operations) {this.operations=operations;}
    @GetMapping("/api/v1/ingestion/deliveries/v1/health")
    ResponseEntity<Map<String,Object>> health() {var health=operations.health();return ResponseEntity.status("UP".equals(health.get("ingestion"))?200:503).body(health);}
}
