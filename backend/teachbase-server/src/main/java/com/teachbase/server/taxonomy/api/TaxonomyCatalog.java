package com.teachbase.server.taxonomy.api;

import java.util.UUID;

/** Named module port for version lifecycle, deterministic lookup, and assignments. */
public interface TaxonomyCatalog {

    TaxonomyVersionResponse createVersion(CreateTaxonomyVersionRequest request);

    TaxonomyNodeResponse createNode(UUID taxonomyVersionId, CreateTaxonomyNodeRequest request);

    TaxonomyVersionResponse activate(UUID taxonomyVersionId, ActivateTaxonomyVersionRequest request);

    TaxonomyNodeResponse resolve(ResolveTaxonomyNodeRequest request);

    QuestionTaxonomyLinkResponse assign(AssignQuestionTaxonomyRequest request);
}
