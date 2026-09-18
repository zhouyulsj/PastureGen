from app.device_ingestion.adapter_base import SensorDataAdapter
from app.device_ingestion.adapter_registry import adapter_registry
from app.device_ingestion.event_models import SensorReadingEvent


@adapter_registry.register
class MockCameraAdapter(SensorDataAdapter):
    adapter_type = "mock_camera"
    vendor = "demo_camera"

    def connect(self) -> None:
        return None

    def collect(self) -> list[SensorReadingEvent]:
        count = float(self.config.get("count", 120.0))
        return [
            SensorReadingEvent(
                device_id=self.device_id or "camera-01",
                metric="herd_count",
                value=count,
                unit="head",
            )
        ]

    def normalize(self, raw: object) -> SensorReadingEvent:
        count = float(raw)
        return SensorReadingEvent(
            device_id=self.device_id or "camera-01",
            metric="herd_count",
            value=count,
            unit="head",
        )