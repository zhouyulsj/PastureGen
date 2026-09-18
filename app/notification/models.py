from pydantic import BaseModel

from app.device_ingestion.event_models import AnimalHealthEvent
from app.perception.alert_repository import Alert, alert_kind


class AlertNotification(BaseModel):
    """推送通道的统一消息载体（与具体告警模型解耦）。"""

    tenant_id: str
    animal_id: str
    kind: str  # health / reproduction
    severity: str  # 健康告警等级 或 繁殖事件类型
    message: str


def notification_from_alert(alert: Alert) -> AlertNotification:
    """把领域告警翻译为推送消息。"""
    if isinstance(alert, AnimalHealthEvent):
        message = (
            f"健康告警: 动物 {alert.animal_id} 指标 {alert.metric}"
            f" = {alert.value}，等级 {alert.severity.value}"
        )
        severity = alert.severity.value
    else:
        message = (
            f"繁殖事件: 动物 {alert.animal_id} 类型 {alert.event_type.value}"
            f"，置信度 {alert.confidence:.2f}"
        )
        severity = alert.event_type.value
    return AlertNotification(
        tenant_id=alert.tenant_id,
        animal_id=alert.animal_id,
        kind=alert_kind(alert),
        severity=severity,
        message=message,
    )
