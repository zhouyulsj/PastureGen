import sqlite3
from pathlib import Path

from app.notification.dead_letter import DeadLetterRecord, DeadLetterRepository


class SqliteDeadLetterRepository(DeadLetterRepository):
    """死信的 SQLite 持久实现（整条记录以 JSON 落库，另建过滤列）。"""

    def __init__(self, db_path: str = "data/push_dead_letter.db") -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS push_dead_letters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                failed_at TEXT NOT NULL,
                data TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_dead_tenant"
            " ON push_dead_letters(tenant_id)"
        )
        self._connection.commit()

    def append(self, record: DeadLetterRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO push_dead_letters (tenant_id, channel, attempts, failed_at, data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                record.notification.tenant_id,
                record.channel,
                record.attempts,
                record.failed_at,
                record.model_dump_json(),
            ),
        )
        self._connection.commit()

    def get(self, record_id: int) -> DeadLetterRecord | None:
        cursor = self._connection.execute(
            "SELECT data FROM push_dead_letters WHERE id = ?", (record_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return DeadLetterRecord.model_validate_json(row[0]).model_copy(
            update={"record_id": record_id}
        )

    def list(
        self,
        tenant_id: str | None = None,
        limit: int | None = None,
    ) -> list[DeadLetterRecord]:
        conditions: list[str] = []
        parameters: list[object] = []
        if tenant_id is not None:
            conditions.append("tenant_id = ?")
            parameters.append(tenant_id)

        statement = "SELECT id, data FROM push_dead_letters"
        if conditions:
            statement += " WHERE " + " AND ".join(conditions)
        statement += " ORDER BY id"
        if limit is not None:
            statement += " LIMIT ?"
            parameters.append(limit)

        cursor = self._connection.execute(statement, parameters)
        return [
            DeadLetterRecord.model_validate_json(data).model_copy(
                update={"record_id": row_id}
            )
            for row_id, data in cursor.fetchall()
        ]

    def delete(self, record_id: int) -> bool:
        cursor = self._connection.execute(
            "DELETE FROM push_dead_letters WHERE id = ?", (record_id,)
        )
        self._connection.commit()
        return cursor.rowcount > 0

    def count(self, tenant_id: str | None = None) -> int:
        statement = "SELECT COUNT(*) FROM push_dead_letters"
        parameters: list[object] = []
        if tenant_id is not None:
            statement += " WHERE tenant_id = ?"
            parameters.append(tenant_id)
        cursor = self._connection.execute(statement, parameters)
        return int(cursor.fetchone()[0])

    def close(self) -> None:
        self._connection.close()
