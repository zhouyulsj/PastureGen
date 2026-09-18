from app.device_ingestion.adapter_base import SensorDataAdapter
from app.device_ingestion.adapter_registry import adapter_registry
from app.device_ingestion.event_models import SensorReadingEvent


@adapter_registry.register
class MockRfidAdapter(SensorDataAdapter):
    adapter_type = "mock_rfid"
    vendor = "demo_rfid"

    def connect(self) -> None:
        return None

    def collect(self) -> list[SensorReadingEvent]:
        animal_id = self.config.get("animal_id", "CN-0001")
        return [
            SensorReadingEvent(
                device_id=self.device_id or "rfid-reader-01",
                metric="rfid_presence",
                value=1.0,
                unit="count",
                animal_id=animal_id,
            )
        ]

    def normalize(self, raw: object) -> SensorReadingEvent:
        tag = str(raw)
        return SensorReadingEvent(
            device_id=self.device_id or "rfid-reader-01",
            metric="rfid_presence",
            value=1.0,
            unit="count",
            animal_id=tag,
        )