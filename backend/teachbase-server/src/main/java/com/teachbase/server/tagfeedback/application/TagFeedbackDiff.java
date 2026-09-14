package com.teachbase.server.tagfeedback.application;

import static com.teachbase.server.tagfeedback.api.TagFeedbackContracts.DerivedOperation;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.springframework.stereotype.Component;

/**
 * 中文维护说明：根据完整 before/after 集合确定性派生操作码，派生结果不是历史事实源。
 */
@Component
public class TagFeedbackDiff {

    public List<DerivedOperation> derive(LabelSet before, LabelSet after) {
        if (before.equals(after)) {
            return List.of(new DerivedOperation("UNCHANGED_CONFIRMED", null, null, null));
        }
        List<DerivedOperation> result = new ArrayList<>();
        if (!java.util.Objects.equals(before.primary(), after.primary())) {
            result.add(new DerivedOperation(
                    "PRIMARY_CHANGED", null, before.primary(), after.primary()));
        }

        Set<UUID> swapped = new LinkedHashSet<>();
        if (before.primary() != null && after.secondary().contains(before.primary())) {
            swapped.add(before.primary());
        }
        if (after.primary() != null && before.secondary().contains(after.primary())) {
            swapped.add(after.primary());
        }
        swapped.stream().sorted(Comparator.comparing(UUID::toString)).forEach(nodeId ->
                result.add(new DerivedOperation(
                        "PRIMARY_SECONDARY_SWAP", nodeId, before.primary(), after.primary())));

        after.secondary().stream()
                .filter(nodeId -> !before.secondary().contains(nodeId) && !swapped.contains(nodeId))
                .sorted(Comparator.comparing(UUID::toString))
                .forEach(nodeId -> result.add(new DerivedOperation(
                        "SECONDARY_ADDED", nodeId, null, null)));
        before.secondary().stream()
                .filter(nodeId -> !after.secondary().contains(nodeId) && !swapped.contains(nodeId))
                .sorted(Comparator.comparing(UUID::toString))
                .forEach(nodeId -> result.add(new DerivedOperation(
                        "SECONDARY_REMOVED", nodeId, null, null)));
        return List.copyOf(result);
    }

    public record LabelSet(UUID primary, Set<UUID> secondary) {
        public LabelSet {
            secondary = Set.copyOf(secondary);
        }
    }
}
