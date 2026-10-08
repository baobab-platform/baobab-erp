"""Executes accepted provisioning operations: claims each due one and runs it to an outcome (ADR-ERP-019).

``POST /provisioning-operations`` accepts a command and answers 202; this is the process that then provisions the legal entities.
Like ``dispatch_worker`` and ``inbox_worker`` it runs to completion and exits, so how often it runs is deployment configuration
(the ``baobab-provisioning-worker`` Compose loop, cron, a systemd timer). It never serves requests. Any number of workers may run:
an operation is claimed with a session advisory lock, so only one at a time works on it (see ``provisioning.execution_store``).

Configuration:
* ``DATABASE_URL`` (required; a direct connection, not a transaction-mode pooler, because the claim is a session lock);
* ``IDEMPIERE_PROVISIONER_CREDENTIALS_JSON``: ``{"<engine_instance_id>": {"base_url", "username", "password", "client_id", "role_id",
  "organization_id"}}``, one provisioner identity per EngineInstance. It is not the per-AD_Client integration credential
  (``IDEMPIERE_CLIENT_CREDENTIALS_JSON``): that AD_Client does not exist until this runs. ADR-ERP-019 §47 forbids a shared
  superuser, so give this identity only the rights client provisioning needs. An operation whose EngineInstance has none is
  *blocked* (retried slowly), not failed;
* ``IDEMPIERE_PROVISIONING_PROCESS_ACCOUNTING`` and ``IDEMPIERE_PROVISIONING_PROCESS_LOCALISATION_JSON`` (see
  ``provisioning.native_processes``): both or neither;
* ``BAOBAB_PROVISIONING_BATCH_LIMIT`` (default 10 operations per run).

One JSON line is written per run: what the pass did and the backlog by status, so an alert can watch ``blocked`` outcomes and the age
of ``planned`` operations.

Not done here: handing the new AD_Client its own integration credentials (``IDEMPIERE_CLIENT_CREDENTIALS_JSON`` is still deployment
configuration that order execution reads), and any run against a live iDempiere.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Callable

import psycopg

from integration.idempiere_client import IdempiereCredentials, RestIdempiereClient
from provisioning.execution import ProvisioningExecutor
from provisioning.execution_store import ConfirmingTenantMappings, PostgresProvisioningExecutionQueue
from provisioning.native_mapping_store import PostgresNativeProvisioningMappingStore
from provisioning.native_processes import NativeProvisioningProcesses, load_native_processes
from provisioning.store import PostgresProvisioningStore


def load_provisioner_credentials(raw: str | None) -> dict[str, IdempiereCredentials]:
    if not raw:
        return {}
    parsed: dict[str, IdempiereCredentials] = {}
    for engine_instance_id, fields in json.loads(raw).items():
        parsed[str(engine_instance_id)] = IdempiereCredentials(
            base_url=fields["base_url"], username=fields["username"], password=fields["password"],
            client_id=int(fields["client_id"]), role_id=int(fields["role_id"]), organization_id=int(fields["organization_id"]))
    return parsed


def engine_factory(credentials: dict[str, IdempiereCredentials]) -> Callable[[str], RestIdempiereClient | None]:
    sessions: dict[str, RestIdempiereClient] = {}

    def engine_for(engine_instance_id: str):
        found = credentials.get(engine_instance_id)
        if found is None:
            return None
        if engine_instance_id not in sessions:  # one session per EngineInstance per run: the client holds its tokens
            sessions[engine_instance_id] = RestIdempiereClient(found)
        return sessions[engine_instance_id]

    return engine_for


def run_once(connection: psycopg.Connection, engine_for, processes: NativeProvisioningProcesses | None, *, limit: int = 10,
             now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    queue = PostgresProvisioningExecutionQueue(connection)
    store = PostgresProvisioningStore(connection)
    executor = ProvisioningExecutor(
        store=store, mappings=PostgresNativeProvisioningMappingStore(connection),
        tenant_mappings=ConfirmingTenantMappings(connection), engine_for=engine_for, processes=processes)
    done: dict[str, int] = {}
    codes: dict[str, int] = {}
    contended = 0
    for provisioning_id in queue.due(limit):
        if not queue.try_lock(provisioning_id):
            contended += 1
            continue
        try:
            operation = queue.begin(provisioning_id)
            if operation is None:
                continue
            outcome = queue.settle(operation, executor.run(operation), store=store, now=now())
            done[outcome.status] = done.get(outcome.status, 0) + 1
            codes[outcome.code] = codes.get(outcome.code, 0) + 1
        finally:
            queue.unlock(provisioning_id)
    return {"event": "provisioning.execute", "pass": done, "codes": codes, "contended": contended, "backlog": queue.backlog()}


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set")
    limit = int(os.environ.get("BAOBAB_PROVISIONING_BATCH_LIMIT", "10"))
    if limit < 1:
        raise RuntimeError("BAOBAB_PROVISIONING_BATCH_LIMIT must be >= 1")
    engine_for = engine_factory(load_provisioner_credentials(os.environ.get("IDEMPIERE_PROVISIONER_CREDENTIALS_JSON")))
    with psycopg.connect(database_url) as connection:
        report = run_once(connection, engine_for, load_native_processes(), limit=limit)
    print(json.dumps(report, sort_keys=True), file=sys.stdout, flush=True)


if __name__ == "__main__":
    main()
