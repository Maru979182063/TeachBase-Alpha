package com.teachbase.server.review.api;

import java.util.UUID;

/** Named module port for opening and deciding review cases without persistence coupling. */
public interface ReviewWorkflow {

    ReviewCaseResponse open(OpenReviewCaseRequest request);

    ReviewCaseResponse decide(UUID reviewCaseId, DecideReviewCaseRequest request);
}
