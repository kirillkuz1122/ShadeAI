import re

from app.core.config import settings

PRIVATE_APPS = {
    "org.telegram.messenger",
    "com.whatsapp",
    "com.sberbank.mobile",
    "ru.sberbankmobile",
    "com.android.mms",
    "com.google.android.apps.messaging",
}
SENSITIVE_CONTENT = re.compile(
    r"\b(?:код\w*|парол\w*|пин\w*|code|otp|pin|password|cvv|cvc)\b", re.IGNORECASE
)


def allowed_apps() -> set[str]:
    return set(settings.notification_allowed_apps) - PRIVATE_APPS


def can_store(app_name: str, title: str, text: str) -> bool:
    return app_name in allowed_apps() and not SENSITIVE_CONTENT.search(title + "\n" + text)
