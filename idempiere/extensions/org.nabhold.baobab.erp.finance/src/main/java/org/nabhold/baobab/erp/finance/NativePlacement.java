package org.nabhold.baobab.erp.finance;

/**
 * One approved, in-force version of an ERP-owned native placement
 * (ADR-ERP-022): where the CP operating Organisation is placed. It never
 * creates authority; CP must still authorise each operation for the same
 * Organisation and legal entity.
 */
public record NativePlacement(String placementId, int version, String tenantId, String engineInstanceId,
                              String operatingOrganisationId, String legalEntityId, String market,
                              int adClientId, int adOrgId) {}
