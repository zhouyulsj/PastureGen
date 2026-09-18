from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field



def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SensorReadingEvent(BaseModel):
    device_id: str
    metric: str
    value: float
    unit: str
    animal_id: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)
    tenant_id: str = ""


class HealthSeverity(str, Enum):
    normal = "normal"
    warning = "warning"
    critical = "critical"


class AnimalHealthEvent(BaseModel):
    animal_id: str
    metric: str
    value: float
    severity: HealthSeverity = HealthSeverity.normal
    timestamp: datetime = Field(default_factory=utc_now)
    tenant_id: str = ""


class ReproductionEventType(str, Enum):
    estrus = "estrus"
    calving = "calving"


class AnimalReproductionEvent(BaseModel):
    animal_id: str
    event_type: ReproductionEventType
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=utc_now)
    tenant_id: str = ""