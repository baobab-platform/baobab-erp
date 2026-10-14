package org.nabhold.baobab.erp.finance;

import static org.junit.jupiter.api.Assertions.*;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.compiere.model.ModelValidator;
import org.junit.jupiter.api.Test;
import org.osgi.service.event.Event;

/**
 * The veto is delivered as a synchronous OSGi event handler: iDempiere's
 * fireModelChange/fireDocValidate send the event for EVERY AD_Client and veto
 * when a handler adds to event.errorMessages (Gate D: the client-0
 * ModelValidator registration never fired for a real client).
 */
class FinanceActivatorEventTest {
    private static FinanceActivator activator() throws Exception {
        FinanceActivator activator = new FinanceActivator();
        Field slot = FinanceActivator.class.getDeclaredField("validatorClass");
        slot.setAccessible(true);
        slot.set(activator, ModelValidator.class);
        return activator;
    }

    /** The native PO methods the veto reads, as iDempiere's PO declares them. */
    public static final class FakePo {
        private final String table;
        private final int client;
        FakePo(String table, int client) { this.table = table; this.client = client; }
        public String get_TableName() { return table; }
        public int getAD_Client_ID() { return client; }
        public int getAD_Org_ID() { return 11; }
        public int get_ID() { return 1000000; }
        public String get_TrxName() { return "BaobabTrx"; }
        public Object get_Value(String column) { return null; }
    }

    private static Event event(String topic, Object po, List<String> errors) {
        Map<String, Object> properties = new HashMap<>();
        properties.put(FinanceActivator.EVENT_DATA, po);
        properties.put(FinanceActivator.TABLE_NAME_PROPERTY, "GL_Journal");
        if (errors != null) properties.put(FinanceActivator.EVENT_ERROR_MESSAGES, errors);
        return new Event(topic, properties);
    }

    @Test
    void subscribesEveryBeforeAndUnknownTopicAndNoAfterTopic() throws Exception {
        Map<String, FinanceActivator.NativeTopic> topics = activator().beforeTopics();
        assertEquals(new FinanceActivator.NativeTopic(false, ModelValidator.TYPE_BEFORE_NEW), topics.get("adempiere/po/beforeNew"));
        assertEquals(new FinanceActivator.NativeTopic(false, ModelValidator.TYPE_BEFORE_CHANGE), topics.get("adempiere/po/beforeChange"));
        assertEquals(new FinanceActivator.NativeTopic(true, ModelValidator.TIMING_BEFORE_PREPARE), topics.get("adempiere/doc/beforePrepare"));
        assertEquals(new FinanceActivator.NativeTopic(true, ModelValidator.TIMING_BEFORE_COMPLETE), topics.get("adempiere/doc/beforeComplete"));
        assertTrue(topics.containsKey("adempiere/po/beforeDelete"), "an unrecognised timing fails closed");
        assertTrue(topics.containsKey("adempiere/doc/beforePost"), "an unrecognised timing fails closed");
        for (String after : List.of("adempiere/po/afterNew", "adempiere/po/afterChange",
                "adempiere/doc/afterPrepare", "adempiere/doc/afterComplete")) {
            assertFalse(topics.containsKey(after), after + " is an irreversible observation, not a veto point");
        }
        assertFalse(topics.containsKey(""));
        assertFalse(topics.containsKey(null));
    }

    @Test
    void filterCoversEveryProtectedTable() {
        String filter = FinanceActivator.tableFilter();
        assertTrue(filter.startsWith("(|") && filter.endsWith(")"));
        for (String table : NativeFinancePolicy.protectedTables()) {
            assertTrue(filter.contains("(tableName=" + table + ")"), table);
        }
    }

    @Test
    void protectedRuntimeWithoutAuthorityVetoesARealClientThroughTheNativeErrorList() throws Exception {
        List<String> errors = new ArrayList<>();
        activator().handle(event("adempiere/doc/beforeComplete", new FakePo("GL_Journal", 11), errors),
                new FinanceActivator.NativeTopic(true, ModelValidator.TIMING_BEFORE_COMPLETE));
        assertEquals(1, errors.size());
        assertEquals("BAOBAB_NATIVE_FINANCE_DENIED: current CP/IAM/financial authority unavailable", errors.get(0),
                "the real PO was read; only the absent authority denied");
    }

    @Test
    void afterTimingAndUnprotectedTablesAddNothing() throws Exception {
        List<String> errors = new ArrayList<>();
        FinanceActivator activator = activator();
        activator.handle(event("adempiere/doc/afterComplete", new FakePo("GL_Journal", 11), errors),
                new FinanceActivator.NativeTopic(true, ModelValidator.TIMING_AFTER_COMPLETE));
        activator.handle(event("adempiere/po/beforeNew", new FakePo("AD_Note", 11), errors),
                new FinanceActivator.NativeTopic(false, ModelValidator.TYPE_BEFORE_NEW));
        assertTrue(errors.isEmpty());
    }

    @Test
    void unknownTopicMissingRecordAndUnreadableRecordAllVeto() throws Exception {
        List<String> errors = new ArrayList<>();
        FinanceActivator activator = activator();
        activator.handle(event("adempiere/po/beforeSomethingNew", new FakePo("GL_Journal", 11), errors), null);
        activator.handle(event("adempiere/po/beforeNew", null, errors),
                new FinanceActivator.NativeTopic(false, ModelValidator.TYPE_BEFORE_NEW));
        activator.handle(event("adempiere/po/beforeNew", new Object(), errors),
                new FinanceActivator.NativeTopic(false, ModelValidator.TYPE_BEFORE_NEW));
        assertEquals(3, errors.size());
        errors.forEach(e -> assertTrue(e.startsWith("BAOBAB_NATIVE_FINANCE_DENIED"), e));
    }
}
