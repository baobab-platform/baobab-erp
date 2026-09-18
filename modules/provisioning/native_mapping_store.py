class PostgresNativeProvisioningMappingStore:
    def __init__(self, connection) -> None:
        self._connection = connection

    def get_native_id(self, *, provisioning_id: str, resource_key: str) -> int | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """SELECT native_id FROM baobab.erp_provisioning_native_mapping
                   WHERE provisioning_id=%s AND resource_key=%s""",
                (provisioning_id, resource_key),
            )
            row = cursor.fetchone()
        return int(row[0]) if row else None

    def put_native_id(self, *, provisioning_id: str, resource_key: str, native_id: int) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO baobab.erp_provisioning_native_mapping
                   (provisioning_id, resource_key, native_id)
                   VALUES (%s,%s,%s)
                   ON CONFLICT (provisioning_id, resource_key)
                   DO UPDATE SET native_id=EXCLUDED.native_id, updated_at=now()""",
                (provisioning_id, resource_key, native_id),
            )
        self._connection.commit()
