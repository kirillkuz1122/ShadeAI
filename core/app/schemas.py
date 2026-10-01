from pydantic import BaseModel


class NotificationIn(BaseModel):
    app_name: str
    title: str
    text: str
    timestamp: str
    priority: str = "default"
