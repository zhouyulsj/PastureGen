from app.device_ingestion.adapter_base import SensorDataAdapter


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, type[SensorDataAdapter]] = {}

    def register(self, adapter_class: type[SensorDataAdapter]) -> type[SensorDataAdapter]:
        name = adapter_class.adapter_type
        self._adapters[name] = adapter_class
        return adapter_class

    def create(self, name: str, **config) -> SensorDataAdapter:
        if name not in self._adapters:
            raise KeyError(f"未注册的适配器类型: {name}")
        return self._adapters[name](**config)

    def list_adapters(self) -> list[dict]:
        return [
            {"type": cls.adapter_type, "vendor": cls.vendor}
            for cls in self._adapters.values()
        ]


adapter_registry = AdapterRegistry()