package org.nabhold.baobab.erp.outbox;

import java.lang.System.Logger;
import java.lang.System.Logger.Level;
import org.osgi.framework.BundleActivator;
import org.osgi.framework.BundleContext;

/**
 * Registers the Baobab outbox-publication service into iDempiere's OSGi runtime.
 * Production wiring replaces the {@link System.Logger} placeholder with iDempiere's
 * own logging facility (CLogger) once this bundle is installed against a running
 * instance rather than built standalone, matching every other bundle here.
 */
public final class OutboxActivator implements BundleActivator {

    private static final Logger LOG = System.getLogger(OutboxActivator.class.getName());

    @Override
    public void start(BundleContext context) {
        LOG.log(Level.INFO, "Baobab ERP outbox bundle starting");
        context.registerService(OutboxPublisher.class, new BaobabOutboxPublisher(), null);
    }

    @Override
    public void stop(BundleContext context) {
        LOG.log(Level.INFO, "Baobab ERP outbox bundle stopping");
    }
}
