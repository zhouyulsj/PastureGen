import sqlite3
from datetime import datetime
from pathlib import Path

from app.perception.alert_repository import (
    Alert,
    AlertRepository,
    dump_alert,
    load_alert,
)


class SqliteAlertRepository(AlertRepository):
    """告警的 SQLite 持久实现（整条告警以 JSON 落库，另建过滤/冷却列）。"""

    def __init__(self, db_path: str = "data/alert.db") -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                dedup_key TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                data TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_alerts_tenant ON alerts(tenant_id)"
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_alerts_dedup ON alerts(dedup_key, timestamp)"
        )
        self._connection.commit()

    def append(self, alert: Alert) -> None:
        tenant_id, kind, dedup_key, data = dump_alert(alert)
        self._connection.execute(
            """
            INSERT INTO alerts (tenant_id, kind, dedup_key, timestamp, data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (tenant_id, kind, dedup_key, alert.timestamp.isoformat(), data),
        )
        self._connection.commit()

    def list(
        self,
        tenant_id: str | None = None,
        limit: int | None = None,
    ) -> list[Alert]:
        conditions: list[str] = []
        parameters: list[object] = []
        if tenant_id is not None:
            conditions.append("tenant_id = ?")
            parameters.append(tenant_id)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

        if limit is not None:
            # 与事件查询同源问题：ORDER BY timestamp ASC LIMIT n 取到的是最旧 n 条。
            # 告警列表必须给出**最新**记录，故用倒序子查询取最新 n 条后再升序返回。
            statement = (
                "SELECT kind, data FROM ("
                f"SELECT id, timestamp, kind, data FROM alerts{where} "
                "ORDER BY timestamp DESC, id DESC LIMIT ?"
                ") ORDER BY timestamp ASC, id ASC"
            )
            parameters.append(limit)
        else:
            statement = (
                f"SELECT kind, data FROM alerts{where} "
                "ORDER BY timestamp ASC, id ASC"
            )

        cursor = self._connection.execute(statement, parameters)
        return [load_alert(kind, data) for kind, data in cursor.fetchall()]

    def last_timestamp(self, dedup_key: str) -> datetime | None:
        cursor = self._connection.execute(
            "SELECT timestamp FROM alerts WHERE dedup_key = ? ORDER BY timestamp DESC LIMIT 1",
            (dedup_key,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row[0])

    def close(self) -> None:
        self._connection.close()
