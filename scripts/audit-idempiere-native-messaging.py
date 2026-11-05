#!/usr/bin/env python3
"""Read-only public dependency inventory for ADR-ERP-004 emergency upgrades.

This is vendor/OSGi compatibility evidence, NEVER native business acceptance.
No ERP database, broker, tenant, credential or private runtime is inspected.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.error
import urllib.request
import zipfile

CENTRAL = "https://repo.maven.apache.org/maven2"
VERSION = "5.19.12"
ARTIFACTS = tuple(("org/apache/activemq", name, VERSION) for name in (
    "activemq-client", "activemq-broker", "activemq-jaas",
    "activemq-kahadb-store", "activemq-openwire-legacy",
)) + (("jakarta/jms", "jakarta.jms-api", "2.0.3"),)
MAX_JAR = 32 * 1024 * 1024


def read_url(url, maximum):
    with urllib.request.urlopen(url, timeout=45) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("VENDOR_DOWNLOAD_BOUND_EXCEEDED")
    return data


def manifest(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        info = archive.getinfo("META-INF/MANIFEST.MF")
        if info.file_size > 512 * 1024:
            raise ValueError("VENDOR_MANIFEST_BOUND_EXCEEDED")
        value = archive.read(info).decode("utf-8").replace("\r\n", "\n")
    value = value.replace("\n ", "")
    fields = {}
    for line in value.splitlines():
        if ": " in line:
            key, content = line.split(": ", 1)
            if key in ("Bundle-SymbolicName", "Bundle-Version", "Bundle-Activator",
                       "Import-Package", "Export-Package", "Require-Bundle"):
                fields[key] = content
    return fields


def vendor(group, name, version):
    url = f"{CENTRAL}/{group}/{name}/{version}/{name}-{version}.jar"
    data = read_url(url, MAX_JAR)
    verified = None
    # Older Maven releases publish SHA-1 only. Report that exact provenance
    # honestly; the reviewed follow-up pins SHA-256 of these actual bytes.
    for algorithm in ("sha512", "sha256", "sha1"):
        try:
            checksum = read_url(url + "." + algorithm, 4096).decode("ascii").strip().lower()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise
        width = hashlib.new(algorithm).digest_size * 2
        if not re.fullmatch(r"[0-9a-f]{" + str(width) + "}", checksum):
            raise ValueError("VENDOR_CHECKSUM_FORMAT_REFUSED")
        if hashlib.new(algorithm, data).hexdigest() != checksum:
            raise ValueError("VENDOR_CHECKSUM_MISMATCH")
        verified = algorithm
        break
    if verified is None:
        raise ValueError("PUBLISHED_VENDOR_CHECKSUM_REQUIRED")
    return {"artifact": name, "version": version,
            "sha256": hashlib.sha256(data).hexdigest(),
            "published_checksum_verified": verified, "manifest": manifest(data)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugins", type=Path, required=True)
    parser.add_argument("--bundles-info", type=Path, required=True)
    args = parser.parse_args()
    relevant = re.compile(r"activemq|geronimo.*jms|jakarta.*jms|slf4j|hawtbuf", re.I)
    entries = [line for line in args.bundles_info.read_text().splitlines()
               if relevant.search(line)]
    if not any("activemq-client" in line for line in entries):
        raise ValueError("EXPECTED_NATIVE_ACTIVEMQ_CLIENT_ABSENT")
    print("NATIVE_MESSAGING_REGISTRY " + json.dumps(entries, sort_keys=True))
    for jar in sorted(args.plugins.glob("*.jar")):
        if relevant.search(jar.name):
            data = jar.read_bytes()
            if len(data) > MAX_JAR:
                raise ValueError("NATIVE_JAR_BOUND_EXCEEDED")
            print("NATIVE_MESSAGING_BUNDLE " + json.dumps({
                "file": jar.name, "sha256": hashlib.sha256(data).hexdigest(),
                "manifest": manifest(data)}, sort_keys=True))
    for group, name, version in ARTIFACTS:
        print("VENDOR_MESSAGING_BUNDLE " + json.dumps(vendor(group, name, version),
                                                    sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
