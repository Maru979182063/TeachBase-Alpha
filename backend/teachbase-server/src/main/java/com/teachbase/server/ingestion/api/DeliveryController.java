package com.teachbase.server.ingestion.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.ingestion.application.DeliveryContract;
import com.teachbase.server.ingestion.application.DeliveryException;
import com.teachbase.server.ingestion.application.DeliveryService;
import com.teachbase.server.ingestion.application.DeliveryObservation;
import jakarta.servlet.http.HttpServletRequest;
import java.util.UUID;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/** 中文维护说明：版本化同步入口；actor header 仅沿用本地成员校验，不宣称提供正式认证。 */
@RestController
@RequestMapping("/api/v1/ingestion/deliveries/v1")
class DeliveryController {
    private static final org.slf4j.Logger LOG=org.slf4j.LoggerFactory.getLogger(DeliveryController.class);
    private static final int MAX_BODY=16*1024*1024;
    private final DeliveryService service; private final DeliveryContract contract; private final DeliveryObservation observation;
    DeliveryController(DeliveryService service,DeliveryContract contract,DeliveryObservation observation) { this.service=service; this.contract=contract; this.observation=observation; }
    private JsonNode manifest(HttpServletRequest request) throws java.io.IOException {
        byte[] body=request.getInputStream().readNBytes(MAX_BODY+1); if(body.length>MAX_BODY) throw new DeliveryException(413,"delivery_body_too_large"); return contract.parse(body);
    }
    @PostMapping("/preflight")
    JsonNode preflight(@RequestHeader("X-Actor-Id") UUID actor,HttpServletRequest request) throws java.io.IOException { var m=manifest(request);return observation.call("preflight",()->service.preflight(m,actor)); }
    @PostMapping("/imports")
    ResponseEntity<JsonNode> commit(@RequestHeader("X-Actor-Id") UUID actor,HttpServletRequest request) throws java.io.IOException {
        var m=manifest(request);var result=observation.call("import",()->service.commit(m,actor));
        LOG.info("delivery_commit workspace={} request={} package={} items={} replay={}",result.receipt().path("workspaceId").asText(),
            result.receipt().path("importRequestId").asText(),result.receipt().path("packageId").asText(),result.receipt().path("items").size(),result.replay());
        return ResponseEntity.status(result.replay()?200:201).body(result.receipt());
    }
    @GetMapping("/requests/{requestId}")
    JsonNode receipt(@PathVariable UUID requestId,@RequestParam UUID workspaceId,@RequestHeader("X-Actor-Id") UUID actor) { return observation.call("receipt",()->service.receipt(workspaceId,requestId,actor)); }
    @ExceptionHandler(DeliveryException.class)
    ProblemDetail invalid(DeliveryException e) { return ProblemDetail.forStatusAndDetail(org.springframework.http.HttpStatusCode.valueOf(e.status()),e.getMessage()); }
}
