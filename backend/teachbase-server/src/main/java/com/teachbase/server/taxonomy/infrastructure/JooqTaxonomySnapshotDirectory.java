package com.teachbase.server.taxonomy.infrastructure;

import static com.teachbase.jooq.tables.TaxonomyNode.TAXONOMY_NODE;
import static com.teachbase.jooq.tables.TaxonomyVersion.TAXONOMY_VERSION;

import com.teachbase.server.taxonomy.api.TaxonomySnapshotDescriptor;
import com.teachbase.server.taxonomy.api.TaxonomySnapshotDirectory;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.jooq.DSLContext;
import org.springframework.stereotype.Repository;

/**
 * 中文维护说明：只按 workspace 与精确版本读取知识树；返回前会确认请求中的每个节点都属于该版本。
 */
@Repository
class JooqTaxonomySnapshotDirectory implements TaxonomySnapshotDirectory {

    private final DSLContext database;

    JooqTaxonomySnapshotDirectory(DSLContext database) {
        this.database = database;
    }

    @Override
    public Optional<TaxonomySnapshotDescriptor> describe(
            UUID workspaceId, UUID taxonomyVersionId, List<UUID> taxonomyNodeIds) {
        var version = database.selectFrom(TAXONOMY_VERSION)
                .where(TAXONOMY_VERSION.WORKSPACE_ID.eq(workspaceId))
                .and(TAXONOMY_VERSION.TAXONOMY_VERSION_ID.eq(taxonomyVersionId))
                .fetchOne();
        if (version == null) {
            return Optional.empty();
        }
        List<UUID> distinctIds = taxonomyNodeIds.stream()
                .distinct()
                .sorted(java.util.Comparator.comparing(UUID::toString))
                .toList();
        List<UUID> foundIds = distinctIds.isEmpty()
                ? List.of()
                : database.select(TAXONOMY_NODE.TAXONOMY_NODE_ID)
                        .from(TAXONOMY_NODE)
                        .where(TAXONOMY_NODE.WORKSPACE_ID.eq(workspaceId))
                        .and(TAXONOMY_NODE.TAXONOMY_VERSION_ID.eq(taxonomyVersionId))
                        .and(TAXONOMY_NODE.TAXONOMY_NODE_ID.in(distinctIds))
                        .orderBy(TAXONOMY_NODE.TAXONOMY_NODE_ID)
                        .fetch(TAXONOMY_NODE.TAXONOMY_NODE_ID);
        if (foundIds.size() != distinctIds.size()
                || !java.util.Set.copyOf(foundIds).equals(java.util.Set.copyOf(distinctIds))) {
            return Optional.empty();
        }
        return Optional.of(new TaxonomySnapshotDescriptor(
                taxonomyVersionId,
                version.getTaxonomyKey(),
                version.getSubject(),
                version.getStage(),
                version.getStatus(),
                List.copyOf(foundIds)));
    }
}
