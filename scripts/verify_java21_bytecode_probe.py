#!/usr/bin/env python3
"""DEV10-R3 isolated Java 21 classfile check; never release proof.

Accept only Baobab-owned, non-shaded class files from each OSGi module's
target/classes. This is deliberately NOT the deployable JAR contract checker:
production currently retains Java 17 bytecode (major 61) until a separate
iDempiere-v13 runtime/compatibility and deployment approval is completed.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "integration", "context", "mapping", "outbox", "events", "finance"
)
MAJOR_JAVA_21 = 65


def main() -> None:
    for module in MODULES:
        root = (
            ROOT / "idempiere" / "extensions"
            / f"org.nabhold.baobab.erp.{module}" / "target" / "classes"
            / "org" / "nabhold" / "baobab" / "erp"
        )
        if not root.is_dir():
            raise RuntimeError(f"Missing compiled Java 21 module: {module}")
        classes = [
            path for path in root.rglob("*.class")
            if "/internal/" not in path.as_posix()
        ]
        if not classes:
            raise RuntimeError(f"No non-shaded classes in module: {module}")
        for path in classes:
            data = path.read_bytes()[:8]
            if len(data) != 8 or data[:4] != b"\xca\xfe\xba\xbe":
                raise RuntimeError(f"Not a Java class file: {path}")
            major = int.from_bytes(data[6:8], "big")
            if major != MAJOR_JAVA_21:
                raise RuntimeError(
                    f"Unexpected bytecode {major}, expected Java21 major65: {path}"
                )
        print(f"Java 21 bytecode probe: {module}: {len(classes)} classes (major 65)")
    print("Java 21 SOURCE/TEST bytecode probe passed; no runtime or release approved")


if __name__ == "__main__":
    main()
