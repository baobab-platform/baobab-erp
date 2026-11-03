# DEV10-R3 — ERP Java 21 / Maven 3.10 owner compatibility

**Candidate, not a production-runtime migration.** Governance:
EA v2.3 / EA-DEV DEV-10, ADR-ERP-004, ADR-ERP-013, ADR-ERP-020.

## Versions and three different acceptance claims

| Dimension | Evidence exercised by ERP #124 | Status/boundary |
| --- | --- | --- |
| Build JDK | Eclipse Temurin **21**, enforced by Java and javac readbacks | Toolchain proof, not iDempiere support certification |
| Maven | Apache **3.10.0 GA**, fetched directly from the Apache archive and verified with the upstream published SHA-512 | Owner-specific compatibility qualification |
| Deployable OSGi bundles | Reactor `verify` under JDK21/Maven3.10, retaining the checked-in `maven.compiler.release=17` | Preserves class-file major **61** and the existing packaged-contract test |
| Isolated Java21-bytecode probe | After the packaged Java17 artifact check, `clean verify -Dmaven.compiler.release=21` compiles all six Baobab extensions and asserts every owned, non-shaded `.class` has major **65** | **Non-deployable compatibility experiment**, not accepted production artifact |
| Native finance on JDK21 | Real PostgreSQL17 native fixture/migrations and all **39** JDBC Gate B financial-posting fence tests, Java21 bytecode and Maven3.10 | Must not silently skip; separate from live iDempiere runtime |
| Existing owner CI | Real iDempiere Gate D, ERP-A, Shared conformance, container Trivy and Security remain required separately | Those jobs may still use JDK17/other image versions |

The original Java21 unit-only workflow executed 64 non-JDBC finance tests but
reported another **39 PostgreSQL-backed tests skipped**. Independent JDBC
testing under Java17 did not qualify Java21. This PR therefore adds a JDK21
PostgreSQL17 native-finance job with a fail-closed 39-tests-executed assertion.
It also reruns the compatibility gate on extension source and fixture changes,
not only when the workflow YAML changes.

## What is deliberately **not** changed here

- The checked-in production `maven.compiler.release=17`, deployable image,
  versioned iDempiere release, OSGi bundle manifests and signed release
  artifacts remain unchanged. Java21 class-file major65 is **not** compatible
  with a Java17 VM, although Java17 classfiles run on a Java21 VM.
- A green Maven3.10 JVM unit test does not prove that every released iDempiere
  13 plugin, Tycho/Equinox subsystem, third-party localisation, or downstream
  ERP consumer can load Java21-class-file bundles safely.
- `baobab-dev` PR #57's `config/versions.yaml` and `config/versions.lock`
  still pin Maven **3.9.16** at the time of this audit. The Maven3.10 test here
  is therefore **not** proof of a system-wide pinned devcontainer upgrade.
- There is no automatic amendment to ERP financial-posting authority, tenant
  isolation, release policy, PostgreSQL17 migration of persistent data, or
  protected staging/production approval.

**Migration sequence:** qualify this owner-side toolchain and isolated classfile
probe; later separately revise the effective source/runtime bytecode contract,
upgrade the production build JDK and image, execute actual iDempiere-v13 OSGi
runtime and finance/tenant negative scenarios, independently qualify dependent
consumers and security evidence, then approve protected release.

**Evidence ledger:** ERP #124 is only accepted when all its **final-head** CI
workflows, including Maven3.10 checksum/readback, full OSGi reactor, actual
packaged Java17 contract, Java21 major65 probe and 39 JDBC PostgreSQL17 tests
are successful. A queued/ongoing workflow is **NOT PASS**. Preserve failed
logs, manifest/artifact provenance and the precise commit SHA. Neither the
experimental Java21 probe nor a green CI job implies staging/production approval.

Apache Maven 3.10.0 source evidence:
https://maven.apache.org/docs/3.10.0/release-notes.html
