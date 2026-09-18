from abc import ABC, abstractmethod

from app.device_ingestion.event_models import SensorReadingEvent


class SensorDataAdapter(ABC):
    adapter_type: str = "generic"
    vendor: str = "unknown"

    def __init__(self, device_id: str = "", **config):
        self.device_id = device_id
        self.config = config

    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def collect(self) -> list[SensorReadingEvent]:
        raise NotImplementedError

    @abstractmethod
    def normalize(self, raw: object) -> SensorReadingEvent:
        raise NotImplementedError

    def handle_webhook(self, payload: dict) -> SensorReadingEvent:
        return self.normalize(payload)

    def health_check(self) -> dict:
        return {"device_id": self.device_id, "status": "ok"}

    def close(self) -> None:
        return None