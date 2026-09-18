import json

from app.device_ingestion.adapter_registry import adapter_registry
from app.device_ingestion.ingestion_gateway import ingestion_gateway


class MqttIngestionService:
    def __init__(
        self,
        host: str,
        port: int,
        adapter_type: str,
        topic: str,
        tenant_id: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.adapter_type = adapter_type
        self.topic = topic
        self.tenant_id = tenant_id
        self._client = None

    def start(self) -> dict:
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            return {"status": "paho-mqtt-not-installed"}

        self._client = mqtt.Client()
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.connect(self.host, self.port)
        self._client.loop_start()
        return {"status": "started", "topic": self.topic}

    def _on_connect(self, client, userdata, flags, reason_code) -> None:
        client.subscribe(self.topic)

    def _on_message(self, client, userdata, message) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        adapter = adapter_registry.create(self.adapter_type, tenant_id=self.tenant_id)
        event = adapter.handle_webhook(payload)
        ingestion_gateway.ingest([event])

    def stop(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()