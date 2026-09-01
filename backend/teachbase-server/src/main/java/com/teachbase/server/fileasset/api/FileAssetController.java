package com.teachbase.server.fileasset.api;

import com.teachbase.server.fileasset.application.FileRegistrationService;
import com.teachbase.server.fileasset.application.RegisterFileCommand;
import jakarta.validation.Valid;
import java.net.URI;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/files")
/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，只负责 HTTP 协议转换，业务不变量必须留在应用服务中。
 *
 * 英文术语对照：HTTP adapter for portable, checksum-addressed file metadata registration.
 */
class FileAssetController {

    private final FileRegistrationService registrationService;

    FileAssetController(FileRegistrationService registrationService) {
        this.registrationService = registrationService;
    }

    @PostMapping
    ResponseEntity<FileRegistrationResponse> register(@Valid @RequestBody RegisterFileRequest request) {
        var result = registrationService.register(new RegisterFileCommand(
                request.workspaceId(),
                request.actorUserId(),
                request.originalFilename(),
                request.storageProvider(),
                request.storageKey(),
                request.mediaType(),
                request.sizeBytes(),
                request.sha256()));
        var response = FileRegistrationResponse.from(result);
        if (result.created()) {
            return ResponseEntity.created(URI.create("/api/v1/files/" + result.fileAssetId())).body(response);
        }
        return ResponseEntity.ok(response);
    }
}
