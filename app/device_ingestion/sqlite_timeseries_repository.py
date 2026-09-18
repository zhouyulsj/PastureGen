import sqlite3
from pathlib import Path

from app.device_ingestion.event_models import SensorReadingEvent
from app.device_ingestion.timeseries_repository import TimeseriesRepository


class SqliteTimeseriesRepository(TimeseriesRepository):
    def __init__(self, db_path: str = "data/sensor.db") -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sensor_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                metric TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT,
                animal_id TEXT,
                timestamp TEXT NOT NULL,
                tenant_id TEXT
            )
            """
        )
        self._connection.commit()

    def append(self, events: list[SensorReadingEvent]) -> None:
        rows = [
            (
                event.device_id,
                event.metric,
                event.value,
                event.unit,
                event.animal_id,
                event.timestamp.isoformat(),
                event.tenant_id,
            )
            for event in events
        ]
        self._connection.executemany(
            """
            INSERT INTO sensor_readings
                (device_id, metric, value, unit, animal_id, timestamp, tenant_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._connection.commit()

    def query(
        self,
        device_id: str | None = None,
        metric: str | None = None,
        animal_id: str | None = None,
        tenant_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> list[SensorReadingEvent]:
        conditions: list[str] = []
        parameters: list[object] = []
        if device_id is not None:
            conditions.append("device_id = ?")
            parameters.append(device_id)
        if metric is not None:
            conditions.append("metric = ?")
            parameters.append(metric)
        if animal_id is not None:
            conditions.append("animal_id = ?")
            parameters.append(animal_id)
        if tenant_id is not None:
            conditions.append("tenant_id = ?")
            parameters.append(tenant_id)
        if start is not None:
            conditions.append("timestamp >= ?")
            parameters.append(start)
        if end is not None:
            conditions.append("timestamp <= ?")
            parameters.append(end)

        statement = "SELECT device_id, metric, value, unit, animal_id, timestamp, tenant_id FROM sensor_readings"
        if conditions:
            statement += " WHERE " + " AND ".join(conditions)
        statement += " ORDER BY timestamp"
        if limit is not None:
            statement += " LIMIT ?"
            parameters.append(limit)

        cursor = self._connection.execute(statement, parameters)
        return [self._row_to_event(row) for row in cursor.fetchall()]

    def count(self) -> int:
        cursor = self._connection.execute("SELECT COUNT(*) FROM sensor_readings")
        return int(cursor.fetchone()[0])

    def close(self) -> None:
        self._connection.close()

    @staticmethod
    def _row_to_event(row: tuple) -> SensorReadingEvent:
        device_id, metric, value, unit, animal_id, timestamp, tenant_id = row
        return SensorReadingEvent(
            device_id=device_id,
            metric=metric,
            value=value,
            unit=unit,
            animal_id=animal_id,
            timestamp=timestamp,
            tenant_id=tenant_id,
        )