from __future__ import annotations


class PostgresTransactionProjectionMappingStore:
    def __init__(self, connection): self._connection=connection

    def get(self, *, engine_instance_id, legal_entity_id, kind, canonical_id):
        with self._connection.cursor() as c:
            c.execute("""SELECT native_id, desired_digest
              FROM baobab.erp_transaction_projection_mapping
              WHERE engine_instance_id=%s AND legal_entity_id=%s AND resource_kind=%s AND canonical_id=%s""",
              (engine_instance_id,legal_entity_id,kind,canonical_id))
            row=c.fetchone()
        return (int(row[0]),row[1]) if row else None

    def put(self, *, engine_instance_id, legal_entity_id, kind, canonical_id, native_id, digest):
        with self._connection.cursor() as c:
            c.execute("""INSERT INTO baobab.erp_transaction_projection_mapping
              (engine_instance_id,legal_entity_id,resource_kind,canonical_id,native_id,desired_digest)
              VALUES (%s,%s,%s,%s,%s,%s)
              ON CONFLICT (engine_instance_id,legal_entity_id,resource_kind,canonical_id)
              DO UPDATE SET native_id=EXCLUDED.native_id, desired_digest=EXCLUDED.desired_digest, updated_at=now()""",
              (engine_instance_id,legal_entity_id,kind,canonical_id,native_id,digest))
        self._connection.commit()
