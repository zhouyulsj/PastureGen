from datetime import date

from pydantic import BaseModel


class Trait(BaseModel):
    trait_code: str
    name: str
    unit: str
    heritability: float | None = None
    measure_type: str = "continuous"


class PerformanceRecord(BaseModel):
    animal_id: str
    trait_code: str
    value: float
    record_date: date


class PerformanceManager:
    def __init__(self) -> None:
        self._traits: dict[str, Trait] = {}
        self._records: list[PerformanceRecord] = []

    def register_trait(self, trait: Trait) -> None:
        self._traits[trait.trait_code] = trait

    def add_record(self, record: PerformanceRecord) -> None:
        self._records.append(record)

    def list_traits(self) -> list[Trait]:
        return list(self._traits.values())

    def list_records(self, animal_id: str | None = None) -> list[PerformanceRecord]:
        if animal_id is None:
            return list(self._records)
        return [record for record in self._records if record.animal_id == animal_id]