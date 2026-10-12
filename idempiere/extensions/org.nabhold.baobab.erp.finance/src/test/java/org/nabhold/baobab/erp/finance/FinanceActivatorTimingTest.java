package org.nabhold.baobab.erp.finance;

import static org.junit.jupiter.api.Assertions.*;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import org.compiere.model.ModelValidator;
import org.junit.jupiter.api.Test;

class FinanceActivatorTimingTest {
    @Test
    void nativeCallbacksDistinguishBeforeAndAfterAndUseTheirOwnNamespaces() throws Exception {
        FinanceActivator activator = new FinanceActivator();
        Field slot = FinanceActivator.class.getDeclaredField("validatorClass");
        slot.setAccessible(true);
        slot.set(activator, ModelValidator.class);
        Method before = FinanceActivator.class.getDeclaredMethod("isBeforeTiming", boolean.class, int.class);
        before.setAccessible(true);
        Method name = FinanceActivator.class.getDeclaredMethod("constantName", int.class, boolean.class);
        name.setAccessible(true);

        assertEquals(true, before.invoke(activator, false, ModelValidator.TYPE_BEFORE_NEW));
        assertEquals(false, before.invoke(activator, false, ModelValidator.TYPE_AFTER_NEW));
        assertEquals(true, before.invoke(activator, true, ModelValidator.TIMING_BEFORE_PREPARE));
        assertEquals(false, before.invoke(activator, true, ModelValidator.TIMING_AFTER_PREPARE));
        assertEquals("TYPE_BEFORE_NEW", name.invoke(activator, 1, false));
        assertEquals("TIMING_BEFORE_PREPARE", name.invoke(activator, 1, true));
        assertEquals(true, before.invoke(activator, true, 999), "unknown native timings fail closed");
    }
}
