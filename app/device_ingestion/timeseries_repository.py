from abc import ABC, abstractmethod

from app.device_ingestion.event_models import SensorReadingEvent


class TimeseriesRepository(ABC):
    @abstractmethod
    def append(self, events: list[SensorReadingEvent]) -> None:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        raise NotImplementedError