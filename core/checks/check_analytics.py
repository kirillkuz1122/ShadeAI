"""Настоящий Uvicorn/HTTP и перезапуск TASK-20; только синтетическая временная БД."""

import argparse
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

CORE = Path(__file__).resolve().parents[1]
ENTITY = "binary_sensor.synthetic_presence"


def serve(folder, env, port):
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=folder,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return process


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    assert process.returncode in (0, -15), "Uvicorn не завершился штатно"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("Выберите новый output, существующий отчёт не перезаписывается")
    report = {"platform": "development-computer", "synthetic": True, "ha_commands": 0, "runs": []}
    with tempfile.TemporaryDirectory(
        prefix="task20-loopback-", dir=CORE / ".pytest_cache"
    ) as scratch:
        folder = Path(scratch)
        key = secrets.token_urlsafe(32)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(CORE),
            "PYTHONUTF8": "1",
            "SHADE_API_KEY": key,
            "DB_URL": f"sqlite+aiosqlite:///{folder / 'synthetic.db'}",
            "HA_BASE_URL": "http://127.0.0.1:1",
            "HA_TOKEN": "",
            "LLM_ENABLED": "false",
            "NOTIFICATION_PROCESSOR": "disabled",
            "HA_TELEMETRY_ENTITIES": json.dumps([ENTITY]),
            "ANALYTICS_PRESENCE_ENTITY": ENTITY,
            "ANALYTICS_TIMEZONE": "UTC",
            "ANALYTICS_INTERVAL_SECONDS": "60",
            "LOG_DIR": str(folder / "logs"),
        }
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(CORE / "alembic.ini"), "upgrade", "head"],
            cwd=folder,
            env=env,
            check=True,
            timeout=30,
            stdout=subprocess.DEVNULL,
        )
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=28)
        with sqlite3.connect(folder / "synthetic.db") as db:
            rows = [
                (ENTITY, "on", "{}", "ha_snapshot", None, start.replace(tzinfo=None).isoformat(" "))
            ]
            for day in range(28):
                for hour, value in ((8, "off"), (18, "on")):
                    stamp = (start + timedelta(days=day, hours=hour)).replace(tzinfo=None)
                    rows.append(
                        (
                            ENTITY,
                            value,
                            "{}",
                            "ha_state_changed",
                            stamp.isoformat(" "),
                            stamp.isoformat(" "),
                        )
                    )
            db.executemany(
                "INSERT INTO sensor_history(entity_id,state,attributes_json,source,"
                "ha_timestamp,observed_at) VALUES (?,?,?,?,?,?)",
                rows,
            )
            db.execute(
                "INSERT INTO telemetry_checkpoint VALUES (?,?)",
                (1, datetime.now(UTC).replace(tzinfo=None).isoformat(" ")),
            )
        previous_ids = None
        for _ in range(2):
            with socket.socket() as address:
                address.bind(("127.0.0.1", 0))
                port = address.getsockname()[1]
            process = serve(folder, env, port)
            try:
                began = time.monotonic()
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=2
                ) as client:
                    while True:
                        assert process.poll() is None, "Core завершился до готовности"
                        assert time.monotonic() - began < 20, "Анализатор не стал ready"
                        try:
                            response = client.get(
                                "/api/v1/habits", headers={"Authorization": f"Bearer {key}"}
                            )
                            data = response.json()
                            if data["analytics"]["status"] == "ready":
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(0.05)
                    assert client.get("/api/v1/habits").status_code == 401
                    assert len(data["habits"]) == 4 and not data["analytics"]["stale"]
                    assert data["analytics"]["action_authorized"] is False
                    ids = [item["id"] for item in data["habits"]]
                    if previous_ids is not None:
                        assert ids == previous_ids
                    previous_ids = ids
                    health = client.get("/api/v1/health").json()
                    assert health["db_connected"] and health["services"]["analytics"] == "ready"
                    assert health["llm_status"] == "not_loaded"
                    report["runs"].append(
                        {
                            "profiles": len(ids),
                            "ids": ids,
                            "eligible_days": data["analytics"]["diagnostics"]["eligible_days"],
                            "startup_to_result_ms": round((time.monotonic() - began) * 1000, 2),
                            "telemetry_stale": data["analytics"]["telemetry_stale"],
                        }
                    )
            finally:
                stop(process)
        with sqlite3.connect(folder / "synthetic.db") as db:
            assert db.execute("SELECT COUNT(*) FROM events_log").fetchone()[0] == 0
        report["restart"] = "PASS"
        report["http_auth_health"] = "PASS"
        report["gguf_required"] = False
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
