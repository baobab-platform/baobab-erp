package org.nabhold.baobab.erp.finance;

import static org.junit.jupiter.api.Assertions.*;
import java.sql.Connection;
import java.time.Instant;
import java.time.LocalDate;
import org.junit.jupiter.api.Test;

/** Offline negative tests; native PostgreSQL + iDempiere qualification is independent. */
class NativeLedgerFactsTest {
    private NativeLedgerFacts.Scope scope() {
        return new NativeLedgerFacts.Scope("tn_example", "EXAMPLE-LE",
                "2c8e4f6a-1b3d-4e5f-8a7c-9d0e1f2a3b4c",
                11, 11, 101, "UGX", LocalDate.parse("2026-10-01"),
                LocalDate.parse("2026-10-31"), Instant.now());
    }

    @Test void refusesAbsentOrNegativeCurrentAuthorityBeforeDatabaseRead() {
        NativeLedgerFacts reader = new NativeLedgerFacts();
        FakeJdbc fake = new FakeJdbc();
        assertThrows(SecurityException.class, () -> reader.read(fake.connection(), scope(), null));
        assertThrows(SecurityException.class, () -> reader.read(fake.connection(), scope(), unused -> false));
        assertTrue(fake.queries.isEmpty());
    }

    @Test void refusesAutocommitAndWeakSnapshotEvenWithSyntheticPermit() {
        NativeLedgerFacts reader = new NativeLedgerFacts();
        FakeJdbc fake = new FakeJdbc();
        fake.autoCommit = true;
        assertThrows(SecurityException.class, () -> reader.read(fake.connection(), scope(), unused -> true));
        fake.autoCommit = false; // FakeJdbc has no independently certified transaction isolation.
        assertThrows(SecurityException.class, () -> reader.read(fake.connection(), scope(), unused -> true));
        assertTrue(fake.queries.isEmpty());
    }

    @Test void rejectsCurrencyPeriodAndMissingIdentity() {
        var s = scope();
        assertThrows(IllegalArgumentException.class, () -> new NativeLedgerFacts.Scope(
                s.tenantId(), s.legalEntityId(), s.operatingOrganisationId(), 11, 11, 101,
                "ugx", s.periodStart(), s.periodEnd(), s.asOf()));
        assertThrows(IllegalArgumentException.class, () -> new NativeLedgerFacts.Scope(
                s.tenantId(), s.legalEntityId(), s.operatingOrganisationId(), 11, 11, 101,
                "UGX", s.periodEnd(), s.periodStart(), s.asOf()));
        assertThrows(IllegalArgumentException.class, () -> new NativeLedgerFacts.Scope(
                "", s.legalEntityId(), s.operatingOrganisationId(), 11, 11, 101,
                "UGX", s.periodStart(), s.periodEnd(), s.asOf()));
    }
}
