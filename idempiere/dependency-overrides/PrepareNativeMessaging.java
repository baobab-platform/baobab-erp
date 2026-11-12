import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;
import java.util.jar.Attributes;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.jar.JarOutputStream;
import java.util.jar.Manifest;

/**
 * ADR-ERP-004 temporary third-party OSGi adaptation; never patches iDempiere.
 * Vendor JAR bytes remain intact inside a native-symbolic-name wrapper. The
 * official client's external imports/uses remain exact. Other wrappers retain upstream
 * iDempiere's optional-package policy while requiring JMS/SLF4J when used.
 */
public final class PrepareNativeMessaging {
    private static final String VERSION = "5.19.12";
    // Public Maven archive digest, never an API credential.
    private static final String JMS_DIGEST = "5940937cb1095764a0039dae147395e37528a0575e2366f4dd20713b7785044a";
    private static final Map<String, String> HASHES = Map.of(
        "activemq-client", "d433eb32bfda4c3ec20fcf4dfb8cd2b256fb3fde52f14f16aebdf99822840770",
        "activemq-jaas", "10953cccc30fbd281c91223898974322fc518c39f2887e4bbe4e1683008445f0",
        "activemq-kahadb-store", "02ce2410091653e23c0603f52a958612b1a1f77ebf6706acb875907f0d38d9ae",
        "activemq-openwire-legacy", "fa7dccbcc2bdc3089c8c5a762498aa66241055bf97317b3f901e471a618f4874",
        "jakarta.jms-api", JMS_DIGEST);

    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("input/output directories required");
        Path input = Path.of(args[0]), output = Path.of(args[1]);
        Files.createDirectories(output);
        TreeSet<String> familyPackages = new TreeSet<>();
        for (String artifact : new TreeSet<>(HASHES.keySet())) {
            String version = artifact.equals("jakarta.jms-api") ? "2.0.3" : VERSION;
            Path file = input.resolve(artifact + "-" + version + ".jar");
            byte[] bytes = Files.readAllBytes(file);
            if (bytes.length > 32 * 1024 * 1024 || !HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(bytes)).equals(HASHES.get(artifact))) {
                throw new IllegalArgumentException("pinned vendor checksum refused: " + artifact);
            }
            if (!artifact.equals("jakarta.jms-api")) {
                try (JarFile jar = new JarFile(file.toFile())) {
                    var entries = jar.entries();
                    while (entries.hasMoreElements()) {
                        String name = entries.nextElement().getName();
                        if (name.endsWith(".class") && !name.startsWith("META-INF/") && name.contains("/")) {
                            familyPackages.add(name.substring(0, name.lastIndexOf('/')).replace('/', '.'));
                        }
                    }
                }
            }
        }
        for (String artifact : new TreeSet<>(HASHES.keySet())) {
            String version = artifact.equals("jakarta.jms-api") ? "2.0.3" : VERSION;
            Path source = input.resolve(artifact + "-" + version + ".jar");
            byte[] bytes = Files.readAllBytes(source);
            if (bytes.length > 32 * 1024 * 1024 || !HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(bytes)).equals(HASHES.get(artifact))) {
                throw new IllegalArgumentException("pinned vendor checksum refused: " + artifact);
            }
            if (artifact.equals("jakarta.jms-api")) {
                Files.write(output.resolve("jakarta.jms-api_2.0.3.jar"), bytes);
                continue;
            }
            boolean client = artifact.equals("activemq-client");
            String symbolic = (client ? "" : "wrapped.") + "org.apache.activemq." + artifact;
            Manifest manifest;
            try (JarFile jar = new JarFile(source.toFile())) {
                manifest = client ? new Manifest(jar.getManifest()) : new Manifest();
                Attributes headers = manifest.getMainAttributes();
                headers.putValue("Manifest-Version", "1.0");
                headers.putValue("Bundle-ManifestVersion", "2");
                headers.putValue("Bundle-SymbolicName", symbolic);
                headers.putValue("Bundle-Version", VERSION);
                headers.putValue("Bundle-ClassPath", "lib/" + source.getFileName());
                TreeSet<String> exports = new TreeSet<>();
                var entries = jar.entries();
                while (entries.hasMoreElements()) {
                    String name = entries.nextElement().getName();
                    if (name.endsWith(".class") && !name.startsWith("META-INF/") && name.contains("/")) {
                        exports.add(name.substring(0, name.lastIndexOf('/')).replace('/', '.'));
                    }
                }
                if (exports.isEmpty() || exports.size() > 1000) {
                    throw new IllegalArgumentException("vendor package census refused");
                }
                if (client) {
                    // Match the native target's -noimport policy for OWN code.
                    // Otherwise a split util package in KahaDB can replace the
                    // client's own utility classes. External ranges and all
                    // vendor uses constraints are retained without relaxation.
                    headers.putValue("Import-Package", String.join(",", clauses(
                        headers.getValue("Import-Package")).stream().filter(c ->
                            !familyPackages.contains(c.split(";", 2)[0].trim())).toList()));
                } else {
                    // Apache's family shares utility packages. Attach the
                    // native sidecars as ordinary host fragments so one class
                    // space contains their intact vendor archives. Separate
                    // package wires would hide partial util/codec classes.
                    headers.putValue("Fragment-Host", "org.apache.activemq.activemq-client;bundle-version=\"[5.19.12,5.19.13)\"");
                    headers.putValue("Bundle-RequiredExecutionEnvironment", "JavaSE-11");
                    headers.putValue("Export-Package", String.join(",", exports.stream()
                        .map(p -> p + ";version=\"" + VERSION + "\"").toList()));
                    List<String> imports = new ArrayList<>();
                    for (String dependency : dependencies(source)) {
                        if (familyPackages.contains(dependency) || dependency.startsWith("java.")) continue;
                        if (dependency.equals("javax.jms")) {
                            imports.add(dependency + ";version=\"[2.0,3)\"");
                        } else if (dependency.startsWith("org.slf4j")) {
                            imports.add(dependency + ";version=\"[2.0,3)\"");
                        } else {
                            // Same optional policy as the upstream native wrappers;
                            // this neither installs a broker nor enables KahaDB/JAAS.
                            imports.add(dependency + ";resolution:=optional");
                        }
                    }
                    if (!imports.isEmpty()) headers.putValue("Import-Package", String.join(",", imports));
                }
                Path target = output.resolve(symbolic + "_" + VERSION + ".jar");
                // Fixed outer timestamps; the complete original vendor archive
                // (including signatures/licenses) is preserved byte for byte.
                try (JarOutputStream stream = new JarOutputStream(Files.newOutputStream(target))) {
                    ByteArrayOutputStream encoded = new ByteArrayOutputStream();
                    manifest.write(encoded);
                    entry(stream, "META-INF/MANIFEST.MF", encoded.toByteArray());
                    entry(stream, "lib/" + source.getFileName(), bytes);
                }
            }
        }
    }

    private static List<String> clauses(String value) {
        List<String> result = new ArrayList<>();
        int start = 0;
        boolean quoted = false;
        for (int i = 0; i < value.length(); i++) {
            if (value.charAt(i) == '"') quoted = !quoted;
            else if (value.charAt(i) == ',' && !quoted) {
                result.add(value.substring(start, i));
                start = i + 1;
            }
        }
        result.add(value.substring(start));
        return result;
    }

    private static void entry(JarOutputStream stream, String path, byte[] bytes) throws Exception {
        JarEntry entry = new JarEntry(path);
        entry.setTime(0L);
        stream.putNextEntry(entry);
        stream.write(bytes);
        stream.closeEntry();
    }

    private static TreeSet<String> dependencies(Path source) throws Exception {
        Process process = new ProcessBuilder(Path.of(System.getProperty("java.home"), "bin", "java").toString(),
            "--module", "jdk.jdeps/com.sun.tools.jdeps.Main", "--ignore-missing-deps",
            "--multi-release", "base", "-verbose:package", source.toString())
            .redirectErrorStream(true).start();
        String result;
        try (InputStream stream = process.getInputStream()) {
            result = new String(stream.readNBytes(2_000_001), StandardCharsets.UTF_8);
        }
        if (result.length() > 2_000_000 || process.waitFor() != 0) {
            throw new IllegalArgumentException("vendor dependency analysis refused");
        }
        TreeSet<String> packages = new TreeSet<>();
        for (String line : result.split("\n")) {
            String[] parts = line.trim().split("\\s+");
            if (parts.length >= 3 && parts[1].equals("->")
                    && parts[2].matches("[a-zA-Z_$][\\w$]*(\\.[a-zA-Z_$][\\w$]*)+")) packages.add(parts[2]);
        }
        return packages;
    }
}
