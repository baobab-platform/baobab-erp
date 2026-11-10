from __future__ import annotations
from typing import Protocol


class MasterDataMappingStore(Protocol):
    def get(
        self, *, engine_instance_id: str, legal_entity_id: str, kind: str, canonical_id: str
    ) -> tuple[int, str, str] | None: ...

    def put(
        self,
        *,
        engine_instance_id: str,
        legal_entity_id: str,
        kind: str,
        canonical_id: str,
        native_id: int,
        desired_digest: str,
        source_version: str,
        commit: bool = True,
    ) -> str:
        pass


class PostgresMasterDataMappingStore:
    def __init__(self, connection): self._connection=connection

    def get(self, *, engine_instance_id, legal_entity_id, kind, canonical_id):
        with self._connection.cursor() as c:
            c.execute("""SELECT native_id, desired_digest, source_version
              FROM baobab.erp_master_data_mapping
              WHERE engine_instance_id=%s AND legal_entity_id=%s AND resource_kind=%s AND canonical_id=%s""",
              (engine_instance_id,legal_entity_id,kind,canonical_id))
            row=c.fetchone()
        return (int(row[0]),row[1],row[2]) if row else None

    def put(self, *, engine_instance_id, legal_entity_id, kind, canonical_id, native_id, desired_digest, source_version,
            commit=True):
        with self._connection.cursor() as c:
            c.execute("""INSERT INTO baobab.erp_master_data_mapping
              (engine_instance_id,legal_entity_id,resource_kind,canonical_id,native_id,desired_digest,source_version)
              VALUES (%s,%s,%s,%s,%s,%s,%s)
              ON CONFLICT (engine_instance_id,legal_entity_id,resource_kind,canonical_id)
              DO UPDATE SET desired_digest=EXCLUDED.desired_digest,
                            source_version=EXCLUDED.source_version, updated_at=now()
              WHERE baobab.erp_master_data_mapping.native_id = EXCLUDED.native_id
              RETURNING erp_resource_id""",
              (engine_instance_id,legal_entity_id,kind,canonical_id,native_id,desired_digest,source_version))
            row = c.fetchone()
            if row is None:
                # A change of native identity is a governed migration, not
                # a retry/upsert. Leave the existing mapping and public ID
                # unchanged, and fail this transaction closed.
                raise ValueError("canonical resource already maps to a different native ERP record")
            public_id = row[0]  # minted on first write; never rekeyed
        if commit:  # an executor writes this in the same transaction as the inbox outcome and commits both itself
            self._connection.commit()
        return public_id
