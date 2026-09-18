from app.device_ingestion.adapter_base import SensorDataAdapter
from app.device_ingestion.adapter_registry import adapter_registry
from app.device_ingestion.event_models import SensorReadingEvent


@adapter_registry.register
class HttpCameraAdapter(SensorDataAdapter):
    adapter_type = "http_camera"
    vendor = "generic_http_camera"

    def connect(self) -> None:
        return None

    def collect(self) -> list[SensorReadingEvent]:
        return []

    def normalize(self, raw: object) -> SensorReadingEvent:
        payload = raw if isinstance(raw, dict) else {}
        return SensorReadingEvent(
            device_id=self.device_id or str(payload.get("device_id") or "camera-01"),
            metric="herd_count",
            value=float(payload.get("count", 0.0)),
            unit="head",
        )