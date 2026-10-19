from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

MAX_NOTIFICATION_BYTES = 65536


class NotificationBodyLimit:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not (
                scope["path"].rstrip("/") in {"/api/v1/notifications", "/api/v1/ha/action"}
                or scope["path"].startswith("/api/v1/automations/")
                or scope["path"].startswith("/api/v1/calendar/")
                or scope["path"].startswith("/api/v1/voice/")
                or scope["path"].startswith("/api/v1/access/")
                or scope["path"].startswith("/api/v1/devices/")
                and scope["path"].rstrip("/").endswith("/command")
            )
        ):
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_NOTIFICATION_BYTES:
                await JSONResponse(
                    status_code=413, content={"detail": "Тело запроса превышает 65536 байт"}
                )(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)
