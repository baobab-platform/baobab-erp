package org.nabhold.baobab.erp.acceptance;

import java.math.BigDecimal;
import java.util.Properties;

import org.adempiere.util.ProcessUtil;
import org.adempiere.util.ServerContext;
import org.compiere.model.MAccount;
import org.compiere.model.MElementValue;
import org.compiere.process.ProcessInfo;
import org.compiere.process.ProcessInfoParameter;
import org.compiere.util.DB;
import org.compiere.util.Env;
import org.compiere.util.Trx;

/**
 * DEV-09 CI-only native company provisioning. This intentionally invokes
 * iDempiere 13's real InitialClientSetup (AD_Process 53161) rather than copying
 * AD_Client/AD_Org catalogue rows. The process provisions the new accounting
 * schema, client info, access roles and organisation through MSetup.
 *
 * It runs ONLY in the disposable ERP-A integration container and DOES NOT
 * authorize any CP tenant, legal actor, native placement or runtime grant.
 * The harness verifies these distinct authorities afterwards.
 */
final class NativeCompanySetup {
    private static final int INITIAL_CLIENT_SETUP = 53161;
    private static final String COMPANY = "DEV09 Independent Company B";
    private static final String ORG = "DEV09-ORG-B";

    private NativeCompanySetup() {}

    static Properties execute(Properties input) {
        Properties result = new Properties();
        if (!"DEV09_SECOND_COMPANY_ONLY".equals(input.getProperty("profile"))) {
            throw new IllegalArgumentException("DEV09_NATIVE_COMPANY_PROFILE_REQUIRED");
        }
        if (DB.getSQLValueEx(null, "SELECT count(*) FROM AD_Client WHERE Name=?", COMPANY) != 0) {
            throw new IllegalStateException("DEV09_NATIVE_COMPANY_ALREADY_PROVISIONED");
        }

        // Account configuration has no permitted native posting class.
        // Fixture bootstrap must finish before governed acceptance starts;
        // never relax the shipped veto to provision a company in that mode.
        if (!"integration".equals(System.getProperty("baobab.erp.native.environment"))) {
            throw new IllegalStateException("DEV09_NATIVE_SETUP_REQUIRES_ISOLATED_BOOTSTRAP");
        }
        int currency = DB.getSQLValueEx(null,
                "SELECT C_Currency_ID FROM C_Currency WHERE ISO_Code='ZAR' AND IsActive='Y'");
        int country = DB.getSQLValueEx(null,
                "SELECT C_Country_ID FROM C_Country WHERE CountryCode='ZA' AND IsActive='Y'");
        if (currency <= 0 || country <= 0) {
            throw new IllegalStateException("DEV09_NATIVE_COUNTRY_CURRENCY_NOT_AVAILABLE");
        }

        // A dedicated system-admin acceptance context; no production actor or
        // human grant is inferred from this synthetic run-scoped process.
        Properties ctx = new Properties();
        Env.setContext(ctx, Env.AD_CLIENT_ID, 0);
        Env.setContext(ctx, Env.AD_ORG_ID, 0);
        Env.setContext(ctx, Env.AD_USER_ID, 100);
        Env.setContext(ctx, Env.AD_ROLE_ID, 0);
        Env.setContext(ctx, Env.LANGUAGE, "en_US");

        ProcessInfo pi = new ProcessInfo("DEV09 Native Initial Client Setup", INITIAL_CLIENT_SETUP);
        pi.setAD_Client_ID(0);
        pi.setAD_User_ID(100);
        pi.setClassName("org.adempiere.process.InitialClientSetup");
        pi.setParameter(new ProcessInfoParameter[] {
                parameter("ClientName", COMPANY),
                parameter("OrgValue", ORG),
                parameter("OrgName", "DEV09 Independent Organisation B"),
                parameter("AdminUserName", "DEV09B-Admin"),
                parameter("NormalUserName", "DEV09B-User"),
                parameter("IsSetInitialPassword", "N"),
                parameter("C_Currency_ID", BigDecimal.valueOf(currency)),
                parameter("C_Country_ID", BigDecimal.valueOf(country)),
                parameter("CityName", "Cape Town"),
                parameter("IsUseBPDimension", "Y"),
                parameter("IsUseProductDimension", "Y"),
                parameter("IsUseProjectDimension", "N"),
                parameter("IsUseCampaignDimension", "N"),
                parameter("IsUseSalesRegionDimension", "N"),
                parameter("IsUseActivityDimension", "N"),
                parameter("UseDefaultCoA", "Y"),
                // Journals must have active default account combinations; no
                // test may silently activate a production account afterwards.
                parameter("InactivateDefaults", "N")
        });

        // InitialClientSetup constructs MSetup from Env.getCtx(), even
        // though ProcessUtil also accepts a ctx argument. Install that same
        // run-owned system context for the native process, then always clear
        // it before the driver handles another request.
        boolean completed;
        ServerContext.setCurrentInstance(ctx);
        try {
            completed = ProcessUtil.startJavaProcess(ctx, pi, null, false);
        } finally {
            ServerContext.dispose();
        }
        if (!completed || pi.isError()) {
            // Do not write process parameters, generated login details or
            // native exception bodies into evidence/logs.
            throw new IllegalStateException("DEV09_NATIVE_INITIAL_CLIENT_SETUP_FAILED");
        }
        int client = DB.getSQLValueEx(null, "SELECT AD_Client_ID FROM AD_Client WHERE Name=?", COMPANY);
        int org = DB.getSQLValueEx(null,
                "SELECT AD_Org_ID FROM AD_Org WHERE AD_Client_ID=? AND Value=?", client, ORG);
        int schema = DB.getSQLValueEx(null,
                "SELECT C_AcctSchema1_ID FROM AD_ClientInfo WHERE AD_Client_ID=?", client);
        if (client <= 11 || org <= 0 || schema <= 0) {
            throw new IllegalStateException("DEV09_NATIVE_ACCOUNTING_SETUP_INCOMPLETE");
        }
        seedJournalAccounts(client, org, schema);
        result.setProperty("client", Integer.toString(client));
        result.setProperty("org", Integer.toString(org));
        result.setProperty("accounting_schema_present", "true");
        result.setProperty("native_setup_process", "53161");
        result.setProperty("native_setup_environment", "integration");
        return result;
    }

    /** Native, synthetic ordinary GL accounts for this disposable company.
     * InitialClientSetup supplies document-control defaults, not a usable
     * manual-journal pair. Never change those defaults' control flags or
     * create accounting configuration after the protected restart.
     */
    private static void seedJournalAccounts(int client, int org, int schema) {
        int element = DB.getSQLValueEx(null,
                "SELECT C_Element_ID FROM C_AcctSchema_Element WHERE C_AcctSchema_ID=? AND ElementType='AC'",
                schema);
        if (element <= 0) throw new IllegalStateException("DEV09_NATIVE_ACCOUNT_ELEMENT_MISSING");
        Properties ctx = new Properties();
        Env.setContext(ctx, Env.AD_CLIENT_ID, client);
        Env.setContext(ctx, Env.AD_ORG_ID, org);
        Env.setContext(ctx, Env.AD_USER_ID, 100); // isolated system fixture bootstrap
        Env.setContext(ctx, Env.AD_ROLE_ID, 0);
        Env.setContext(ctx, Env.LANGUAGE, "en_US");
        String name = Trx.createTrxName("Dev09FixtureAccounts");
        Trx trx = Trx.get(name, true);
        ServerContext.setCurrentInstance(ctx);
        try {
            for (int i = 0; i < 2; i++) {
                MElementValue value = new MElementValue(ctx, "DEV09_GL_" + i,
                        "DEV09 synthetic ordinary GL " + i, "Disposable native journal fixture",
                        "A", "N", false, false, name);
                value.setC_Element_ID(element);
                value.setPostActual(true);
                value.saveEx();
                MAccount account = MAccount.get(ctx, client, org, schema,
                        value.getC_ElementValue_ID(), 0,
                        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, name);
                if (account == null || account.getC_ValidCombination_ID() <= 0) {
                    throw new IllegalStateException("DEV09_NATIVE_JOURNAL_COMBINATION_MISSING");
                }
            }
            trx.commit(true);
        } catch (RuntimeException failed) {
            trx.rollback();
            throw failed;
        } finally {
            trx.close();
            ServerContext.dispose();
        }
    }

    private static ProcessInfoParameter parameter(String name, Object value) {
        return new ProcessInfoParameter(name, value, null, null, null);
    }
}
