package com.teachbase.server.releaseseed.application;

/** Post-import database counts used by verify mode and the machine report. */
public record ReleaseSeedVerification(
        int itemCount,
        int approvedItemCount,
        int questionRevisionCount,
        int reviewDecisionCount,
        int sourceDocumentCount,
        int sourceRegionCount,
        int relationCount,
        int taxonomyLinkCount) {
}
