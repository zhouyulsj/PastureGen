from typing import Protocol

from pydantic import BaseModel

DEFAULT_HOLSTEIN_TRAITS: dict[str, dict] = {
    "milk_yield_305d": {"name": "305天产奶量", "unit": "kg", "direction": "higher", "heritability": 0.30},
    "fat_pct": {"name": "乳脂率", "unit": "%", "direction": "higher", "heritability": 0.50},
    "protein_pct": {"name": "乳蛋白率", "unit": "%", "direction": "higher", "heritability": 0.50},
    "somatic_cell_count": {"name": "体细胞数", "unit": "万个/mL", "direction": "lower", "heritability": 0.15},
    "daily_gain": {"name": "日增重", "unit": "g", "direction": "higher", "heritability": 0.40},
    "conception_rate": {"name": "受胎率", "unit": "%", "direction": "higher", "heritability": 0.10},
}

DEFAULT_ALERT_THRESHOLDS: dict[str, list[float]] = {
    "body_temperature": [38.0, 39.5],
    "rumination_minutes": [300.0, 600.0],
}


class TenantMetadata(BaseModel):
    breed_code: str = "holstein"
    traits: dict[str, dict] = {}
    alert_thresholds: dict[str, list[float]] = {}
    enabled_adapter_types: list[str] = []
    notification_webhook_url: str = ""
    notification_webhook_format: str = "feishu"


class MetadataStore(Protocol):
    def load(self, tenant_id: str) -> TenantMetadata | None:
        ...

    def save(self, tenant_id: str, metadata: TenantMetadata) -> None:
        ...


class TenantMetadataRegistry:
    def __init__(self, store: MetadataStore | None = None) -> None:
        self._store = store
        self._cache: dict[str, TenantMetadata] = {}

    def bind_store(self, store: MetadataStore) -> None:
        self._store = store

    def _persist(self, tenant_id: str, metadata: TenantMetadata) -> None:
        if self._store is not None:
            self._store.save(tenant_id, metadata)

    def _default_metadata(self, breed_code: str) -> TenantMetadata:
        return TenantMetadata(
            breed_code=breed_code,
            traits={
                code: dict(trait)
                for code, trait in DEFAULT_HOLSTEIN_TRAITS.items()
                if breed_code == "holstein"
            },
            alert_thresholds={
                metric: list(bounds)
                for metric, bounds in DEFAULT_ALERT_THRESHOLDS.items()
            },
        )

    def ensure_tenant(self, tenant_id: str, breed_code: str = "holstein") -> TenantMetadata:
        if tenant_id in self._cache:
            return self._cache[tenant_id]
        if self._store is not None:
            loaded = self._store.load(tenant_id)
            if loaded is not None:
                self._cache[tenant_id] = loaded
                return loaded
        metadata = self._default_metadata(breed_code)
        self._cache[tenant_id] = metadata
        self._persist(tenant_id, metadata)
        return metadata

    def get_metadata(self, tenant_id: str) -> TenantMetadata:
        return self.ensure_tenant(tenant_id)

    def set_trait(
        self,
        tenant_id: str,
        trait_code: str,
        name: str,
        unit: str,
        heritability: float | None = None,
    ) -> dict:
        metadata = self.ensure_tenant(tenant_id)
        entry = {"name": name, "unit": unit, "direction": "higher"}
        if heritability is not None:
            entry["heritability"] = heritability
        metadata.traits[trait_code] = entry
        self._persist(tenant_id, metadata)
        return entry

    def set_alert_threshold(self, tenant_id: str, metric: str, low: float, high: float) -> list[float]:
        metadata = self.ensure_tenant(tenant_id)
        metadata.alert_thresholds[metric] = [low, high]
        self._persist(tenant_id, metadata)
        return [low, high]

    def enable_adapter(self, tenant_id: str, adapter_type: str) -> list[str]:
        metadata = self.ensure_tenant(tenant_id)
        if adapter_type not in metadata.enabled_adapter_types:
            metadata.enabled_adapter_types.append(adapter_type)
        self._persist(tenant_id, metadata)
        return metadata.enabled_adapter_types

    def set_notification(
        self,
        tenant_id: str,
        webhook_url: str,
        webhook_format: str = "feishu",
    ) -> dict:
        metadata = self.ensure_tenant(tenant_id)
        metadata.notification_webhook_url = webhook_url
        metadata.notification_webhook_format = webhook_format
        self._persist(tenant_id, metadata)
        return {
            "webhook_url": webhook_url,
            "webhook_format": webhook_format,
        }


tenant_metadata_registry = TenantMetadataRegistry()