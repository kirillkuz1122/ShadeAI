"""Временный Core для проверки Android, без рабочего .env/БД и без HA."""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_KEY = "task09-core-emulator-key-00000000000"


def main() -> None:
    cache = ROOT / "core/.pytest_cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="task09-emulator-", dir=cache) as scratch:
        os.chdir(scratch)
        os.environ.update(
            SHADE_API_KEY=API_KEY,
            DB_URL="sqlite+aiosqlite:///./emulator.db",
            HA_BASE_URL="http://127.0.0.1:1",
            HA_TOKEN="",
            HA_TIMEOUT_SECONDS="0.1",
            EVENT_RETENTION_DAYS="90",
            LOG_DIR="./logs",
            LOG_MAX_BYTES="1048576",
            LOG_BACKUP_COUNT="3",
            NOTIFICATION_RETENTION_DAYS="30",
            NOTIFICATION_ALLOWED_APPS='["ru.ozon.app.android"]',
            CORS_ORIGINS="[]",
            LLM_MODEL_PATH="./missing-test-model.gguf",
        )
        sys.path.insert(0, str(ROOT / "core"))
        import uvicorn

        uvicorn.run(
            "app.main:app",
            host="127.0.0.1",
            port=8000,
            access_log=False,
            log_level="warning",
        )


if __name__ == "__main__":
    main()
