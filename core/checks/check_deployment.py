"""TASK-08: настоящие процессы Core, локальный dist, restart и WAL restore на синтетике."""

import argparse
import asyncio
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
KEY = "task08-synthetic-local-owner-key-00001"
TEXT = "Синтетическая посылка для проверки развёртывания"


async def scenario(folder, browser):
    spec = importlib.util.spec_from_file_location("backup", ROOT / "scripts/sqlite_backup.py")
    backup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backup)
    database = folder / "synthetic.db"
    result = {"hardware": False, "native_model": False, "real_systemd": False}

    async def boot(path):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = dict(
            PATH=os.defpath,
            LANG="C.UTF-8",
            PYTHONDONTWRITEBYTECODE="1",
            SHADE_API_KEY=KEY,
            DB_URL="sqlite+aiosqlite:///" + str(path),
            HA_BASE_URL="http://127.0.0.1:9",
            HA_TIMEOUT_SECONDS="0.1",
            WEB_DIST_PATH=str(ROOT / "web/dist"),
            LOG_DIR=str(folder / "logs"),
        )
        child = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                str(ROOT / "core"),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--workers",
                "1",
                "--no-access-log",
                "--log-level",
                "critical",
            ],
            cwd=folder,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        http = httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5)
        try:
            async with asyncio.timeout(15):
                while True:
                    assert child.poll() is None, "Core завершился до ready"
                    try:
                        if (await http.get("/api/v1/health")).status_code in {200, 503}:
                            break
                    except httpx.ConnectError:
                        pass
                    await asyncio.sleep(0.1)
            return child, http
        except BaseException:
            child.terminate()
            await asyncio.to_thread(child.wait, 10)
            await http.aclose()
            raise

    async def stop(child, http):
        await http.aclose()
        child.terminate()
        try:
            await asyncio.to_thread(child.wait, 10)
        except subprocess.TimeoutExpired:
            child.kill()
            await asyncio.to_thread(child.wait)

    receipt = None
    snapshot = None
    for phase in ("initial", "restart", "restore"):
        child, http = await boot(database)
        try:
            index = await http.get("/")
            assert index.status_code == 200 and "Content-Security-Policy" in index.headers
            for asset in (ROOT / "web/dist/assets").iterdir():
                response = await http.get("/assets/" + asset.name)
                assert (
                    response.status_code == 200 and "immutable" in response.headers["cache-control"]
                )
            assert (await http.get("/docs")).status_code == 404
            assert (await http.get("/api/v1/notifications")).status_code == 401
            auth = {"Authorization": "Bearer " + KEY}
            if receipt is None:
                response = await http.post(
                    "/api/v1/notifications",
                    headers=auth,
                    json=dict(
                        app_name="ru.ozon.app.android",
                        title="Стенд TASK-08",
                        text=TEXT,
                        timestamp=datetime.now(UTC).isoformat(),
                        priority="default",
                    ),
                )
                assert response.status_code == 201
                receipt = response.json()["id"]
                snapshot, metadata = await asyncio.to_thread(
                    backup.backup, database, folder / "backups"
                )
                result["backup"] = metadata
                if browser:
                    cli = [
                        "npx",
                        "--offline",
                        "--yes",
                        "--package",
                        "@playwright/cli",
                        "playwright-cli",
                        "--session",
                        "shade-task08",
                    ]

                    async def command(args, cli=tuple(cli)):
                        process = await asyncio.create_subprocess_exec(
                            *cli,
                            *args,
                            cwd=ROOT / "web",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.STDOUT,
                        )
                        output, _ = await asyncio.wait_for(process.communicate(), 60)
                        assert process.returncode == 0, output.decode()[-2000:]
                        return output.decode()

                    try:
                        await command(
                            ["open", str(http.base_url), "--config=checks/playwright.config.json"]
                        )
                        await command(["snapshot"])
                        output = await command(["run-code", "--filename=checks/deployment.js"])
                        assert "TASK08_BROWSER_PASS" in output, output[-2000:]
                        result["browser"] = "PASS"
                    finally:
                        await command(["close"])
            detail = await http.get(f"/api/v1/notifications/{receipt}", headers=auth)
            assert detail.status_code == 200 and detail.json()["text"] == TEXT
            result[phase] = "PASS"
        finally:
            await stop(child, http)
        if phase == "restart":
            database = folder / "restored/new.db"
            result["restore_copy"] = await asyncio.to_thread(
                backup.copy_database, snapshot, database
            )
    result["result"] = "PASS"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--browser", action="store_true", help="Только уже закэшированный CLI/Chromium"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Отчёт уже существует")
    with tempfile.TemporaryDirectory(prefix="deployment-", dir=ROOT / "core/.pytest_cache") as tmp:
        result = asyncio.run(scenario(Path(tmp), args.browser))
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
