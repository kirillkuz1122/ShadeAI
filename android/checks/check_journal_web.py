"""Веб-часть TASK-13 через существующий Playwright CLI; после check_journal.py."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = Path.home() / ".codex/skills/playwright/scripts/playwright_cli.sh"


def main():
    event = json.loads((ROOT / "android/.gradle/task13-checks/event.json").read_text())
    code = (
        (ROOT / "web/checks/android-journal.js")
        .read_text()
        .replace("__EVENT__", json.dumps(event, ensure_ascii=False))
    )
    assert WRAPPER.is_file(), "Нужен установленный Playwright CLI skill/wrapper"
    output = ROOT / "web/output/playwright"
    output.mkdir(parents=True, exist_ok=True)
    for args in (("open", "http://127.0.0.1:5173"), ("snapshot",), ("run-code", code)):
        subprocess.run(
            [str(WRAPPER), "--session", "shade-task13", *args],
            cwd=ROOT / "web",
            check=True,
        )


if __name__ == "__main__":
    main()
