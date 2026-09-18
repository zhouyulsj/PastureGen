from app.device_ingestion.event_models import (
    AnimalHealthEvent,
    HealthSeverity,
    SensorReadingEvent,
)


class HealthMonitor:
    def __init__(self, thresholds: dict[str, tuple[float, float]] | None = None) -> None:
        self.thresholds = thresholds or {
            "body_temperature": (38.0, 39.5),
            "activity_index": (0.0, 100.0),
            "rumination_minutes": (300.0, 600.0),
        }

    def evaluate_event(self, event: SensorReadingEvent) -> AnimalHealthEvent:
        severity = HealthSeverity.normal
        if event.metric in self.thresholds:
            low, high = self.thresholds[event.metric]
            spread = high - low
            critical_low = low - spread * 0.1
            critical_high = high + spread * 0.1
            if event.value < critical_low or event.value > critical_high:
                severity = HealthSeverity.critical
            elif event.value < low or event.value > high:
                severity = HealthSeverity.warning
        return AnimalHealthEvent(
            animal_id=event.animal_id or "",
            metric=event.metric,
            value=event.value,
            severity=severity,
            tenant_id=event.tenant_id,
        )