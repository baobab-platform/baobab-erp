package org.nabhold.baobab.erp.acceptance;

import java.lang.reflect.Method;
import java.util.Arrays;
import org.osgi.framework.Bundle;
import org.osgi.framework.BundleContext;

/** CI-only actual OSGi/JMS/OpenWire linkage; never sends to a broker or grants authority. */
final class NativeMessagingCompatibility {
    private NativeMessagingCompatibility() {}

    static void verify(BundleContext context) {
        try {
            Bundle client = bundle(context, "org.apache.activemq.activemq-client", "5.19.12");
            client.loadClass("org.apache.activemq.ActiveMQConnectionFactory");
            for (String artifact : new String[]{"jaas", "kahadb-store", "openwire-legacy"}) {
                Bundle other = bundle(context, "wrapped.org.apache.activemq.activemq-" + artifact, "5.19.12");
                // Actual class loading resolves each wrapper, not merely its registry entry.
                String type = switch (artifact) {
                    case "jaas" -> "org.apache.activemq.jaas.GroupPrincipal";
                    case "kahadb-store" -> "org.apache.activemq.store.kahadb.disk.util.DataByteArrayOutputStream";
                    default -> "org.apache.activemq.openwire.v8.MessageMarshaller";
                };
                if (other.getState() != Bundle.RESOLVED || !other.getHeaders()
                        .get("Fragment-Host").startsWith("org.apache.activemq.activemq-client;")) {
                    throw new IllegalStateException("native sidecar is not attached to its fixed host");
                }
                client.loadClass(type);
            }
            Bundle core = Arrays.stream(context.getBundles())
                .filter(b -> "org.adempiere.base".equals(b.getSymbolicName())).findFirst().orElseThrow();
            Class<?> messageApi = client.loadClass("javax.jms.Message");
            if (core.loadClass("javax.jms.Message") != messageApi) {
                throw new IllegalStateException("native core/client JMS class spaces differ");
            }
            client.loadClass("javax.jms.JMSContext"); // Actual JMS 2 capability, not a version string.
            client.loadClass("org.apache.activemq.ActiveMQConnectionFactory")
                .getConstructor(String.class).newInstance("tcp://127.0.0.1:1"); // No connect call.
            Class<?> messageType = client.loadClass("org.apache.activemq.command.ActiveMQTextMessage");
            Object message = messageType.getConstructor().newInstance();
            messageType.getMethod("setText", String.class).invoke(message, "baobab-native-codec-smoke");
            messageType.getMethod("setStringProperty", String.class, String.class)
                .invoke(message, "baobabCompatibility", "same-native-api");
            Object wire = client.loadClass("org.apache.activemq.openwire.OpenWireFormat")
                .getConstructor().newInstance();
            Object encoded = wire.getClass().getMethod("marshal", Object.class).invoke(wire, message);
            Method unmarshal = wire.getClass().getMethod("unmarshal",
                client.loadClass("org.apache.activemq.util.ByteSequence"));
            Object decoded = unmarshal.invoke(wire, encoded);
            if (!"baobab-native-codec-smoke".equals(messageType.getMethod("getText").invoke(decoded))
                    || !"same-native-api".equals(messageType.getMethod("getStringProperty", String.class)
                        .invoke(decoded, "baobabCompatibility"))) {
                throw new IllegalStateException("native codec roundtrip differs");
            }
            System.out.println("DEV11_NATIVE_MESSAGING_OSGI_JMS_OPENWIRE=PASS");
        } catch (ReflectiveOperationException | RuntimeException | LinkageError failed) {
            // No provider/driver data is echoed; failed actual linkage prevents readiness.
            throw new IllegalStateException("NATIVE_MESSAGING_OSGI_COMPATIBILITY_REFUSED");
        }
    }

    private static Bundle bundle(BundleContext context, String name, String version) {
        return Arrays.stream(context.getBundles()).filter(b -> name.equals(b.getSymbolicName())
            && version.equals(b.getVersion().toString())).findFirst().orElseThrow();
    }
}
