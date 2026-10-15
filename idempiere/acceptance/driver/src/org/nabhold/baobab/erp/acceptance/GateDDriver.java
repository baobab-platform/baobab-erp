package org.nabhold.baobab.erp.acceptance;

import java.io.IOException;
import java.io.Reader;
import java.io.Writer;
import java.math.BigDecimal;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.List;
import java.util.Properties;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import org.adempiere.util.ServerContext;
import org.compiere.Adempiere;
import org.compiere.model.MJournal;
import org.compiere.model.MJournalLine;
import org.compiere.process.DocAction;
import org.compiere.process.DocumentEngine;
import org.compiere.util.DB;
import org.compiere.util.Env;
import org.compiere.util.Trx;
import org.osgi.framework.BundleActivator;
import org.osgi.framework.BundleContext;

/**
 * EA v2.1 Gate D driver — CI ONLY, never shipped. It is added by
 * idempiere/acceptance/Dockerfile on top of the real Baobab image and drives
 * REAL iDempiere 13 GL journal completion and posting (Doc_GLJournal ->
 * Fact_Acct) through the installed Baobab native finance veto. It holds no
 * authority: every decision comes from the veto, the synthetic CP and the
 * database fence. The CI job reads the outcomes and asserts persisted state.
 *
 * Protocol: a request file requests/<name>.properties (action=journal, org,
 * amount, complete, post, rollbackAfterPost, parallel; or action=doc with
 * kind=order|shipment|invoice|payment|allocation, completeDoc (optionally
 * holdSeconds and hold_marker) and repostDoc with table and id, see SalesFlow;
 * or action=pdoc for the purchase side, see PurchaseFlow) produces
 * results/<name>.properties.
 */
public final class GateDDriver implements BundleActivator, Runnable {
    private static final Path ROOT = Path.of("/opt/idempiere/.baobab/gate-d");
    private static final int CLIENT = 11;
    private static final int GL_JOURNAL_TABLE = 224;
    private volatile boolean running = true;
    private Thread worker;

    @Override
    public void start(BundleContext context) {
        worker = new Thread(this, "baobab-gate-d-driver");
        worker.setDaemon(true);
        worker.start();
    }

    @Override
    public void stop(BundleContext context) {
        running = false;
        if (worker != null) worker.interrupt();
    }

    @Override
    public void run() {
        try {
            Files.createDirectories(ROOT.resolve("requests"));
            Files.createDirectories(ROOT.resolve("results"));
            while (running && !(Adempiere.isStarted() && DB.isConnected())) Thread.sleep(1000);
            Files.writeString(ROOT.resolve("ready"), "ready\n");
            while (running) {
                try (DirectoryStream<Path> requests = Files.newDirectoryStream(ROOT.resolve("requests"), "*.properties")) {
                    for (Path request : requests) handle(request);
                }
                Thread.sleep(500);
            }
        } catch (InterruptedException stopped) {
            Thread.currentThread().interrupt();
        } catch (IOException broken) {
            broken.printStackTrace();
        }
    }

    private void handle(Path request) throws IOException {
        Properties in = new Properties();
        try (Reader r = Files.newBufferedReader(request)) {
            in.load(r);
        }
        Files.delete(request);
        String name = request.getFileName().toString().replace(".properties", "");
        Properties out = new Properties();
        try {
            // Every parse is inside this try: a malformed request is reported, never kills the driver.
            int parallel = Integer.parseInt(in.getProperty("parallel", "1"));
            String action = in.getProperty("action", "journal");
            if ("pdoc".equals(action)) {
                // ERP-A (ADR-SHARED-037): the purchase side and vendor-payment recording.
                Properties ctx = context(Integer.parseInt(in.getProperty("org", "11")));
                try {
                    out.putAll(PurchaseFlow.document(in, ctx));
                } finally {
                    ServerContext.dispose();
                }
            } else if ("doc".equals(action) || "completeDoc".equals(action) || "repostDoc".equals(action)) {
                // P0-04B-05: the other catalogued classes, on the real sales flow.
                Properties ctx = context(Integer.parseInt(in.getProperty("org", "11")));
                try {
                    out.putAll("doc".equals(action) ? SalesFlow.document(in, ctx)
                            : "completeDoc".equals(action) ? SalesFlow.completeExisting(in, ctx)
                            : SalesFlow.repost(in, ctx));
                } finally {
                    ServerContext.dispose();
                }
            } else if ("complete".equals(action)) {
                out.putAll(completeExisting(in));
            } else if ("repost".equals(action)) {
                out.putAll(repost(in));
            } else if (parallel <= 1) {
                out.putAll(journal(in, ""));
            } else {
                ExecutorService pool = Executors.newFixedThreadPool(parallel);
                List<Future<Properties>> runs = new ArrayList<>();
                for (int i = 0; i < parallel; i++) {
                    String prefix = "run" + i + ".";
                    runs.add(pool.submit((Callable<Properties>) () -> journal(in, prefix)));
                }
                for (Future<Properties> run : runs) out.putAll(run.get());
                pool.shutdown();
            }
        } catch (Exception failed) {
            out.setProperty("driver_error", String.valueOf(failed));
        }
        Path tmp = ROOT.resolve("results").resolve(name + ".tmp");
        try (Writer w = Files.newBufferedWriter(tmp)) {
            out.store(w, "Gate D synthetic driver outcome");
        }
        Files.move(tmp, ROOT.resolve("results").resolve(name + ".properties"), StandardCopyOption.ATOMIC_MOVE);
    }

    private static Properties context(int org) {
        Properties ctx = new Properties();
        Env.setContext(ctx, Env.AD_CLIENT_ID, CLIENT);
        Env.setContext(ctx, Env.AD_ORG_ID, org);
        Env.setContext(ctx, Env.AD_USER_ID, 101);   // GardenAdmin
        Env.setContext(ctx, Env.AD_ROLE_ID, 102);   // GardenWorld Admin
        Env.setContext(ctx, Env.LANGUAGE, "en_US");
        Env.setContext(ctx, "#Date", new Timestamp(System.currentTimeMillis()));
        ServerContext.setCurrentInstance(ctx);
        return ctx;
    }

    /** Create a balanced two-line GL journal and complete/post it as requested. */
    private static Properties journal(Properties in, String prefix) {
        Properties out = new Properties();
        int org = Integer.parseInt(in.getProperty("org", "11"));
        BigDecimal amount = new BigDecimal(in.getProperty("amount", "100.00"));
        boolean complete = Boolean.parseBoolean(in.getProperty("complete", "true"));
        boolean post = Boolean.parseBoolean(in.getProperty("post", "true"));
        boolean rollbackAfterPost = Boolean.parseBoolean(in.getProperty("rollbackAfterPost", "false"));
        Properties ctx = context(org);
        String trxName = Trx.createTrxName("BaobabGateD");
        Trx trx = Trx.get(trxName, true);
        int id = 0;
        try {
            int schema = DB.getSQLValueEx(null, "SELECT C_AcctSchema1_ID FROM AD_ClientInfo WHERE AD_Client_ID=?", CLIENT);
            Timestamp today = new Timestamp(System.currentTimeMillis());
            MJournal j = new MJournal(ctx, 0, trxName);
            j.setAD_Org_ID(org);
            j.setC_AcctSchema_ID(schema);
            j.setC_DocType_ID(DB.getSQLValueEx(null, "SELECT MIN(C_DocType_ID) FROM C_DocType WHERE AD_Client_ID=? AND DocBaseType='GLJ' AND IsActive='Y'", CLIENT));
            j.setGL_Category_ID(DB.getSQLValueEx(null, "SELECT MIN(GL_Category_ID) FROM GL_Category WHERE AD_Client_ID=? AND CategoryType='M'", CLIENT));
            j.setC_Currency_ID(DB.getSQLValueEx(null, "SELECT C_Currency_ID FROM C_AcctSchema WHERE C_AcctSchema_ID=?", schema));
            j.setC_ConversionType_ID(DB.getSQLValueEx(null, "SELECT MIN(C_ConversionType_ID) FROM C_ConversionType WHERE IsDefault='Y' AND AD_Client_ID IN (0, ?)", CLIENT));
            j.setDateDoc(today);
            j.setDateAcct(today);
            j.setPostingType("A");
            j.setDescription("Baobab Gate D synthetic journal (CI only)");
            j.saveEx();
            id = j.get_ID();
            out.setProperty(prefix + "journal_id", String.valueOf(id));
            // Two ordinary GL accounts: active, non-summary, actual-posting and
            // NOT document-controlled (bank/AR/AP accounts reject manual journals).
            line(j, 0, amount, true);
            line(j, 1, amount, false);
            if (complete) {
                boolean ok = j.processIt(DocAction.ACTION_Complete);
                out.setProperty(prefix + "complete_ok", String.valueOf(ok));
                if (!ok) out.setProperty(prefix + "complete_msg", String.valueOf(j.getProcessMsg()));
                j.saveEx();
            }
            if (rollbackAfterPost) {
                // Injected failure AFTER Fact_Acct rows were written in this
                // transaction and BEFORE commit: nothing may survive.
                String err = DocumentEngine.postImmediate(ctx, CLIENT, GL_JOURNAL_TABLE, id, true, trxName);
                int facts = DB.getSQLValueEx(trxName, "SELECT COUNT(*) FROM Fact_Acct WHERE AD_Table_ID=? AND Record_ID=?", GL_JOURNAL_TABLE, id);
                out.setProperty(prefix + "facts_before_rollback", String.valueOf(facts));
                out.setProperty(prefix + "post_error", String.valueOf(err));
                trx.rollback();
                out.setProperty(prefix + "committed", "false");
            } else {
                out.setProperty(prefix + "committed", String.valueOf(trx.commit(true)));
                if (complete && post) {
                    String err = DocumentEngine.postImmediate(ctx, CLIENT, GL_JOURNAL_TABLE, id, false, null);
                    out.setProperty(prefix + "post_error", String.valueOf(err));
                }
            }
        } catch (Exception failed) {
            trx.rollback();
            out.setProperty(prefix + "error", String.valueOf(failed.getMessage()));
        } finally {
            trx.close();
            ServerContext.dispose();
        }
        return out;
    }

    /** Complete (and post) a journal drafted earlier, under whatever CP decision applies now. */
    private static Properties completeExisting(Properties in) {
        Properties out = new Properties();
        int id = Integer.parseInt(in.getProperty("journal_id"));
        Properties ctx = context(Integer.parseInt(in.getProperty("org", "11")));
        String trxName = Trx.createTrxName("BaobabGateD");
        Trx trx = Trx.get(trxName, true);
        try {
            MJournal j = new MJournal(ctx, id, trxName);
            boolean ok = j.processIt(DocAction.ACTION_Complete);
            out.setProperty("complete_ok", String.valueOf(ok));
            if (!ok) out.setProperty("complete_msg", String.valueOf(j.getProcessMsg()));
            j.saveEx();
            out.setProperty("committed", String.valueOf(trx.commit(true)));
            if (ok) {
                out.setProperty("post_error", String.valueOf(
                        DocumentEngine.postImmediate(ctx, CLIENT, GL_JOURNAL_TABLE, id, false, null)));
            }
        } catch (Exception failed) {
            trx.rollback();
            out.setProperty("error", String.valueOf(failed.getMessage()));
        } finally {
            trx.close();
            ServerContext.dispose();
        }
        return out;
    }

    /**
     * Post an already posted journal again. Without force the ledger must not
     * duplicate; with force iDempiere deletes and rebuilds Fact_Acct in its OWN
     * posting transaction, exactly as the background accounting processor does.
     */
    private static Properties repost(Properties in) {
        Properties out = new Properties();
        int id = Integer.parseInt(in.getProperty("journal_id"));
        boolean force = Boolean.parseBoolean(in.getProperty("force", "false"));
        Properties ctx = context(11);
        try {
            out.setProperty("post_error", String.valueOf(
                    DocumentEngine.postImmediate(ctx, CLIENT, GL_JOURNAL_TABLE, id, force, null)));
        } catch (Exception failed) {
            out.setProperty("error", String.valueOf(failed.getMessage()));
        } finally {
            ServerContext.dispose();
        }
        return out;
    }

    private static void line(MJournal j, int rank, BigDecimal amount, boolean debit) {
        int combination = DB.getSQLValueEx(null, """
                SELECT x.id FROM (
                SELECT DISTINCT ON (ev.Value) vc.C_ValidCombination_ID AS id, ev.Value AS v FROM C_ValidCombination vc
                  JOIN C_ElementValue ev ON ev.C_ElementValue_ID = vc.Account_ID
                 WHERE vc.AD_Client_ID=? AND vc.AD_Org_ID IN (0, ?) AND vc.C_AcctSchema_ID=?
                   AND vc.IsActive='Y' AND ev.IsActive='Y' AND ev.IsSummary='N'
                   AND ev.IsDocControlled='N' AND ev.PostActual='Y'
                   AND vc.C_BPartner_ID IS NULL AND vc.M_Product_ID IS NULL AND vc.C_Project_ID IS NULL
                 ORDER BY ev.Value, vc.AD_Org_ID DESC, vc.C_ValidCombination_ID) x
                 ORDER BY x.v OFFSET ? LIMIT 1""",
                CLIENT, j.getAD_Org_ID(), j.getC_AcctSchema_ID(), rank);
        if (combination <= 0) {
            throw new IllegalStateException("no ordinary GL account combination for rank " + rank);
        }
        MJournalLine l = new MJournalLine(j);
        l.setC_ValidCombination_ID(combination);
        if (debit) l.setAmtSourceDr(amount); else l.setAmtSourceCr(amount);
        l.saveEx();
    }
}
