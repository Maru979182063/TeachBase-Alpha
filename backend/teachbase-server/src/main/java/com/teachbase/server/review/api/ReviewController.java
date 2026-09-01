package com.teachbase.server.review.api;

import com.teachbase.server.review.application.ReviewService;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 中文维护说明：本文件属于人工审核模块的对外稳定合同层，只负责 HTTP 协议转换，业务不变量必须留在应用服务中。
 *
 * 英文术语对照：HTTP boundary for opening and deciding explicit question review cases.
 */
@RestController
@RequestMapping("/api/v1/review-cases")
class ReviewController {

    private final ReviewService service;

    ReviewController(ReviewService service) {
        this.service = service;
    }

    @PostMapping
    ResponseEntity<ReviewCaseResponse> open(@Valid @RequestBody OpenReviewCaseRequest request) {
        return ResponseEntity.ok(service.open(request));
    }

    @PostMapping("/{reviewCaseId}/decisions")
    ResponseEntity<ReviewCaseResponse> decide(
            @PathVariable UUID reviewCaseId,
            @Valid @RequestBody DecideReviewCaseRequest request) {
        return ResponseEntity.ok(service.decide(reviewCaseId, request));
    }
}
