# DEV10-R3 Java 21 — ERP iDempiere owner compatibility

Java **21** is the candidate *build JDK* for Baobab ERP OSGi bundles.
The ERP reactor currently declares `maven.compiler.release=17` for its
iDempiere-compatible bytecode. This is not a JDK17 runtime downgrade:
the probe compiles and executes tests with Java21 while preserving the
current production engine's bytecode contract. Raising that compiler
target requires independent iDempiere-v13 runtime proof, not wishful thinking.

The existing CI's native finance/PostgreSQL and iDempiere integration fences
remain separate owner gates. A green Java21 module build is **not** evidence
of a live iDempiere runtime, a qualified financial posting, or staging.
Keep the production Java17 source image until the DEV10-R4 full ARM64/AMD64
image has been scanned and actual ERP/Subscriptions native tests passed.
