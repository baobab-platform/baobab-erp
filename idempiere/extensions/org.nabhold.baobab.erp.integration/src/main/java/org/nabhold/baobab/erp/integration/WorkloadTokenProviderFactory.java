package org.nabhold.baobab.erp.integration;

/**
 * Builds a {@link WorkloadTokenProvider} from system properties, the same
 * configuration mechanism {@code BaobabContextResolver}/{@code
 * BaobabMappingResolver} already use for {@code baobab.app.base.url} (not yet
 * exposed through OSGi ConfigurationAdmin -- see architecture/conformance.yaml
 * against ADR-ERP-002).
 *
 * <p>Returns {@code null} when {@link #CLIENT_SECRET_PROPERTY} isn't set, so a
 * {@link BaobabAppClient} built from it sends no Authorization header -- this only
 * works against a baobab-app build that doesn't enforce the workload-token gate
 * (e.g. a test's fake server), never a real deployment, since baobab-app itself now
 * requires one (ADR-0014 §111, Gate IAM-10). A real deployment failing to set this
 * property surfaces immediately as every context/mapping call getting a 401 from
 * baobab-app, not as a silent bypass.
 */
public final class WorkloadTokenProviderFactory {

    public static final String TOKEN_URL_PROPERTY = "baobab.iam.token.url";
    public static final String CLIENT_ID_PROPERTY = "baobab.iam.workload.client.id";
    public static final String CLIENT_SECRET_PROPERTY = "baobab.iam.workload.client.secret";
    public static final String SCOPE_PROPERTY = "baobab.iam.workload.scope";

    private static final String DEFAULT_CLIENT_ID = "baobab-erp-workload";
    private static final String DEFAULT_SCOPE = "erp:integrate";

    private WorkloadTokenProviderFactory() {
    }

    /**
     * A workload client secret: read from the file named by {@code <property>.file}
     * (a mounted secret) when that is set, else from {@code <property>} itself. The
     * file form keeps the secret off the JVM command line, which the iDempiere start
     * script echoes to the container log and which {@code ps} shows. A file that is
     * set but unreadable, empty or multi-line yields {@code null}, never a fallback
     * to the inline property.
     */
    public static String secret(String property) {
        String file = System.getProperty(property + ".file");
        if (file == null || file.isBlank()) {
            return System.getProperty(property);
        }
        try {
            String value = java.nio.file.Files.readString(java.nio.file.Path.of(file)).strip();
            return value.isEmpty() || value.contains("\n") || value.contains("\r") ? null : value;
        } catch (java.io.IOException | RuntimeException unreadable) {
            return null;
        }
    }

    public static WorkloadTokenProvider fromSystemProperties() {
        String clientSecret = secret(CLIENT_SECRET_PROPERTY);
        if (clientSecret == null || clientSecret.isBlank()) {
            return null;
        }
        String tokenUrl = System.getProperty(TOKEN_URL_PROPERTY);
        if (tokenUrl == null || tokenUrl.isBlank()) {
            throw new IllegalStateException(
                    CLIENT_SECRET_PROPERTY + " is set but " + TOKEN_URL_PROPERTY + " is not");
        }
        String clientId = System.getProperty(CLIENT_ID_PROPERTY, DEFAULT_CLIENT_ID);
        String scope = System.getProperty(SCOPE_PROPERTY, DEFAULT_SCOPE);
        return new WorkloadTokenProvider(tokenUrl, clientId, clientSecret, scope);
    }
}
