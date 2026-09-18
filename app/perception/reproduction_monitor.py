from statistics import mean

from app.device_ingestion.event_models import (
    AnimalReproductionEvent,
    ReproductionEventType,
    SensorReadingEvent,
)


class ReproductionMonitor:
    def __init__(self, estrus_activity_ratio: float = 2.0, calving_temperature_drop: float = 0.5) -> None:
        self.estrus_activity_ratio = estrus_activity_ratio
        self.calving_temperature_drop = calving_temperature_drop

    def detect_estrus(
        self, recent_activity: list[SensorReadingEvent], baseline_activity: float
    ) -> AnimalReproductionEvent | None:
        if not recent_activity:
            return None
        peak = max(event.value for event in recent_activity)
        animal_id = recent_activity[0].animal_id or ""
        tenant_id = recent_activity[0].tenant_id
        if baseline_activity > 0 and peak >= self.estrus_activity_ratio * baseline_activity:
            return AnimalReproductionEvent(
                animal_id=animal_id,
                event_type=ReproductionEventType.estrus,
                confidence=0.8,
                tenant_id=tenant_id,
            )
        return None

    def detect_calving(
        self, recent_temperature: list[SensorReadingEvent], baseline_temperature: float
    ) -> AnimalReproductionEvent | None:
        if not recent_temperature:
            return None
        current = mean(event.value for event in recent_temperature)
        animal_id = recent_temperature[0].animal_id or ""
        tenant_id = recent_temperature[0].tenant_id
        if baseline_temperature - current >= self.calving_temperature_drop:
            return AnimalReproductionEvent(
                animal_id=animal_id,
                event_type=ReproductionEventType.calving,
                confidence=0.7,
                tenant_id=tenant_id,
            )
        return None