package com.teachbase.server.exporting.api;

import com.teachbase.server.exporting.application.CreateExportCommand;
import com.teachbase.server.exporting.application.ExportRequestService;
import jakarta.validation.Valid;
import java.net.URI;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/exports")
/**
 * 中文维护说明：本文件属于稳定导出与渲染队列模块的对外稳定合同层，只负责 HTTP 协议转换，业务不变量必须留在应用服务中。
 *
 * 英文术语对照：HTTP adapter for durable export admission and status polling.
 */
class ExportRequestController {

    private final ExportRequestService service;

    ExportRequestController(ExportRequestService service) {
        this.service = service;
    }

    @PostMapping
    ResponseEntity<ExportRequestResponse> create(@Valid @RequestBody CreateExportRequest request) {
        var state = service.create(new CreateExportCommand(
                request.workspaceId(), request.actorUserId(), request.editorSnapshotId(), request.format(),
                request.idempotencyKey(), request.retryOfExportRequestId()));
        var response = ExportRequestResponse.from(state);
        if (state.created()) {
            return ResponseEntity.created(URI.create("/api/v1/exports/" + state.exportRequestId())).body(response);
        }
        return ResponseEntity.ok(response);
    }

    @GetMapping("/{exportRequestId}")
    ExportRequestDetailsResponse get(
            @PathVariable UUID exportRequestId,
            @RequestParam UUID workspaceId,
            @RequestParam UUID actorUserId) {
        return ExportRequestDetailsResponse.from(service.get(exportRequestId, workspaceId, actorUserId));
    }
}
