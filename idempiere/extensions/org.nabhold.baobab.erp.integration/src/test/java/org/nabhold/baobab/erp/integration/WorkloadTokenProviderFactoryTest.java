package org.nabhold.baobab.erp.integration;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/** A workload secret comes from a mounted file when one is named, never silently from the command line. */
class WorkloadTokenProviderFactoryTest {
    private static final String PROPERTY = "baobab.test.workload.client.secret";

    @TempDir
    Path dir;

    @AfterEach
    void clear() {
        System.clearProperty(PROPERTY);
        System.clearProperty(PROPERTY + ".file");
    }

    @Test
    void inlinePropertyIsUsedWhenNoFileIsNamed() {
        System.setProperty(PROPERTY, "inline-secret");
        assertEquals("inline-secret", WorkloadTokenProviderFactory.secret(PROPERTY));
    }

    @Test
    void namedFileWinsAndIsTrimmed() throws Exception {
        Path file = Files.writeString(dir.resolve("secret"), "file-secret\n");
        System.setProperty(PROPERTY, "inline-secret");
        System.setProperty(PROPERTY + ".file", file.toString());
        assertEquals("file-secret", WorkloadTokenProviderFactory.secret(PROPERTY));
    }

    @Test
    void unreadableEmptyOrMultiLineFileYieldsNoSecretAndNeverFallsBack() throws Exception {
        System.setProperty(PROPERTY, "inline-secret");
        System.setProperty(PROPERTY + ".file", dir.resolve("missing").toString());
        assertNull(WorkloadTokenProviderFactory.secret(PROPERTY));
        System.setProperty(PROPERTY + ".file", Files.writeString(dir.resolve("empty"), "  \n").toString());
        assertNull(WorkloadTokenProviderFactory.secret(PROPERTY));
        System.setProperty(PROPERTY + ".file", Files.writeString(dir.resolve("two"), "a\nb\n").toString());
        assertNull(WorkloadTokenProviderFactory.secret(PROPERTY));
    }
}
