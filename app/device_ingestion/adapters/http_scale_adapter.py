from app.device_ingestion.adapter_base import SensorDataAdapter
from app.device_ingestion.adapter_registry import adapter_registry
from app.device_ingestion.event_models import SensorReadingEvent


@adapter_registry.register
class HttpScaleAdapter(SensorDataAdapter):
    adapter_type = "http_scale"
    vendor = "generic_http_scale"

    def connect(self) -> None:
        return None

    def collect(self) -> list[SensorReadingEvent]:
        return []

    def normalize(self, raw: object) -> SensorReadingEvent:
        payload = raw if isinstance(raw, dict) else {}
        return SensorReadingEvent(
            device_id=self.device_id or str(payload.get("device_id") or "scale-01"),
            metric="body_weight",
            value=float(payload.get("weight_kg", 0.0)),
            unit="kg",
            animal_id=payload.get("animal_id"),
        )