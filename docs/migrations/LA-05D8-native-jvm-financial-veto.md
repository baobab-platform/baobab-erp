# LA-05D8 — iDempiere 13 synchronous native JVM finance veto

**Scope:** Native iDempiere ModelValidationEngine registration, before-save/before-document mutation checks, protected runtime fail-closed behaviour. **Not** an operational acceptance or legal/financial certification.

## Executable extension

`org.nabhold.baobab.erp.finance` is an OSGi bundle deployed through the image's Maven build and Equinox `bundles.info`. Its `FinanceActivator` registers one synchronous OSGi `EventHandler` for every BEFORE model and document topic of the *runtime's actual* iDempiere 13 API (`ModelValidator.tableEventTopics`/`documentEventTopics`, correlated with its own `TYPE_`/`TIMING_` constants, never hardcoded), filtered to the protected tables. `ModelValidationEngine.fireModelChange`/`fireDocValidate` deliver these with `EventAdmin.sendEvent` in the saving thread for **every** `AD_Client`, and a message the handler adds to `event.errorMessages` vetoes the save or document action. It **does not** depend on post-commit (`postEvent`) events.

> **Correction (P0-04B Gate D, 2026-10-14).** This bundle previously registered through `ModelValidationEngine.addModelChange`/`addDocValidate` and this document called those listeners globally scoped. They were not: the engine keys such a listener by `table + listener.getAD_Client_ID()` unless it is in its private global list (filled only from `AD_ModelValidator` rows), so a listener reporting client 0 fired for System records only. The real iDempiere Gate D run showed zero CP calls for GardenWorld (client 11) postings; only the database COMMIT fence (ADR-ERP-022) refused them. Fixed by the event-handler registration above, registered directly with the BundleContext (iDempiere's handler blacklist cannot disable it); activation fails without an EventAdmin.

The table policy covers `C_Order`, `C_Invoice`, `C_Payment`, `M_InOut`, native financial detail, allocation, chart, tax, bank, journal and `Fact_Acct` model operations. Both new and changed native POs, deletes, completion/posting and reversal triggers must have fresh exact actor/client/org/record/transaction/action authority. Failure, missing service and unknown deployment environment deny.

The only possible positive permit comes from `NativeFinancialAuthority`, a server-owned OSGi authority port: its implementation must verify *live* IAM-authenticated CP legal mandate, documentary clearance, iDempiere company/period/tax/accounting baseline and operation scope. This PR does **not** supply an implementation of that port; consequently all protected financial mutations are deliberately refused. No user-entered document field, header or synthetic fixture can supply this authority. Development/test/integration use an explicitly configured local-only environment for offline tests.

## Deployment hard gate still missing

An OSGi bundle **installed** in an image is not by itself proof it is **ACTIVE** at iDempiere startup, nor that it observes every entry point or accounting engine path. Before protected acceptance:

1. Supply a real independently governed `NativeFinancialAuthority` provider bound to CP/IAM and ERP finance readiness, with security-reviewed service-provider identity.
2. The image now checks the active JVM PID marker, written only after listener registration, before reporting container health. Protected acceptance must still verify that its orchestration refuses traffic to unhealthy containers, exercises *actual* native callbacks, and prevents direct database bypass. A copied JAR or Docker health result alone does not prove all transaction entry points are covered.
3. Confirm native iDempiere 13 direct UI, REST, batch/import, scheduled jobs, reversals and posting `Fact_Acct` against real engine and database, including alternative table/procedure bypasses.
4. Persist immutable verified legal/accounting attribution through native transactions and canonical finance outbox; this PR does **not** implement attribution columns or a certified posting allow decision.
5. Restrict direct database and iDempiere system/admin credentials separately. Model validation hooks are not database triggers and cannot veto direct SQL writes.
6. Verify the exact iDempiere 13 plugin runtime, startup levels, P2 REST bundle presence and genuine installed build. No AWS, merchant/provider or legal registration claims are made.

**Verdict:** Native JVM **veto implementation and container health registration check** now exist, but live positive authorization, trusted runtime activation proof, attribution, covered-bypass proof and protected production acceptance remain blocked.
