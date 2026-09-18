from app.device_ingestion.adapter_base import SensorDataAdapter
from app.device_ingestion.adapter_registry import adapter_registry
from app.device_ingestion.event_models import SensorReadingEvent


@adapter_registry.register
class ModbusScaleAdapter(SensorDataAdapter):
    adapter_type = "modbus_scale"
    vendor = "generic_modbus_scale"
    register_address: int = 0

    def __init__(self, device_id: str = "", **config):
        super().__init__(device_id, **config)
        self.register_address = int(self.config.get("register_address", 0))
        self._client = None

    def connect(self) -> None:
        try:
            from pymodbus.client import ModbusTcpClient
        except ImportError:
            self._client = None
            return
        host = self.config.get("host", "localhost")
        port = int(self.config.get("port", 502))
        self._client = ModbusTcpClient(host, port=port)
        self._client.connect()

    def collect(self) -> list[SensorReadingEvent]:
        if self._client is None:
            return []
        result = self._client.read_holding_registers(self.register_address, count=1)
        if result.isError():
            return []
        return [self.normalize(float(result.registers[0]))]

    def normalize(self, raw: object) -> SensorReadingEvent:
        value = raw.get("weight_kg", 0.0) if isinstance(raw, dict) else float(raw)
        return SensorReadingEvent(
            device_id=self.device_id or "modbus-scale-01",
            metric="body_weight",
            value=value,
            unit="kg",
            animal_id=self.config.get("animal_id"),
        )

    def health_check(self) -> dict:
        try:
            import pymodbus  # noqa: F401

            dependency = "ok"
        except ImportError:
            dependency = "missing"
        return {"device_id": self.device_id, "status": "ok", "pymodbus": dependency}

    def close(self) -> None:
        if self._client is not None:
            self._client.close()