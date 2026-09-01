package com.teachbase.server.question.api;

import java.util.List;
import java.util.UUID;

/** Cross-module read port for concrete revisions; callers must never resolve "latest" implicitly. */
public interface QuestionRevisionDirectory {

    List<QuestionRevisionDescriptor> findAll(UUID workspaceId, List<UUID> questionRevisionIds);
}
