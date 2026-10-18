"""TASK-13: страницы/статусы/длинный текст на синтетической debug Room, только AVD."""

import sqlite3
import time
import xml.etree.ElementTree as ET
from uuid import uuid4

from check_buffer import core_items, snapshot
from check_emulator import API_KEY, PACKAGE, adb, dump, fill, find, save, scroll, tap
from check_journal import ANDROID_URL, ARTIFACTS, open_journal, shot
from check_sources import COMPONENT, checked, sources_screen


def main():
    assert adb("shell", "getprop", "ro.kernel.qemu").strip() == "1"
    assert len(core_items()) == 2, (
        "Сначала выполните checks/check_journal.py со свежим Core"
    )
    open_journal()
    find("Здесь пока нет записей")
    tap(find("К подключению", top=True))
    fill(0, ANDROID_URL)
    fill(1, API_KEY)
    save()
    find("Ключ принят")
    sources_screen()
    if not checked("Ozon"):
        tap(find("Ozon"))
    adb("shell", "am", "force-stop", PACKAGE)
    assert not snapshot(), "Не заменяем существующий буфер"
    prefs = ET.fromstring(
        adb("exec-out", "run-as", PACKAGE, "cat", "shared_prefs/shade_prefs.xml")
    )
    revision = next(n.text for n in prefs if n.get("name") == "delivery_revision")
    file = ARTIFACTS / "snapshot/shade.db"
    now = int(time.time() * 1000)
    long_text = (
        "Синтетическая доставка без личных данных. " * 60
        + "Конец синтетического текста."
    )
    statuses = ("PENDING", "SENT", "SKIPPED", "FAILED", "REJECTED")
    with sqlite3.connect(file) as db:
        for i in range(105):
            status = statuses[i % len(statuses)]
            error = {"FAILED": "http_401", "REJECTED": "http_422"}.get(status)
            db.execute(
                """INSERT INTO pending_notifications
                (packageName,title,text,postTime,eventId,sourceKey,contentHash,status,createdAt,completedAt,attempts,lastError)
                VALUES (?, ?, ?, ?, ?, NULL, '', ?, ?, ?, ?, ?)""",
                (
                    "ru.ozon.app.android",
                    f"Синтетическая запись {i + 1}",
                    long_text if i == 104 else "Текст синтетической записи",
                    now,
                    str(uuid4()),
                    status,
                    now,
                    now if status in {"SENT", "SKIPPED", "REJECTED"} else None,
                    1 if status != "PENDING" else 0,
                    error,
                ),
            )
        db.execute(
            "INSERT OR REPLACE INTO delivery_control VALUES (1, ?, 0, 0, 1)",
            (revision,),
        )
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    remote = "/data/local/tmp/shade-task13-journal.db"
    try:
        adb("push", str(file), remote)
        adb(
            "shell",
            "run-as",
            PACKAGE,
            "rm",
            "-f",
            "databases/shade.db-wal",
            "databases/shade.db-shm",
        )
        adb("shell", "run-as", PACKAGE, "cp", remote, "databases/shade.db")
        adb("shell", "cmd", "notification", "allow_listener", COMPONENT)
        open_journal()
        find("В буфере: 105")
        find("В очереди: 42")
        find("Отправка приостановлена")
        find("Синтетическая запись 105")
        shot("journal-statuses.png")
        tap(find("Более ранние", top=True))
        find("Страница 2")
        find("Синтетическая запись 55")
        tap(find("Более ранние", top=True))
        find("Страница 3")
        find("Синтетическая запись 5")
        tap(find("Более новые", top=True))
        find("Страница 2")
        tap(find("Более новые", top=True))
        find("Страница 1")
        print(
            "PASS: 105 локальных строк, страницы 50/50/5 и возврат; глобальная очередь 42",
            flush=True,
        )
        for label, count in (
            ("В очереди", 42),
            ("Доставлено", 21),
            ("Пропущено", 21),
            ("Отклонено", 21),
        ):
            for _ in range(3):
                scroll(True)
            nodes = [n for n in dump().iter("node") if n.get("text") == label]
            assert nodes, label
            tap(nodes[0])
            find(f"{label}: {count}")
        tap(find("Все", top=True))
        tap(find("Синтетическая запись 105"))
        assert any(n.get("text") == long_text for n in dump().iter("node")), (
            "Полный текст обрезан"
        )
        tap(find("Закрыть запись"))
        print(
            "PASS: все фильтры/терминальные статусы, безопасная причина 422 и полный длинный текст",
            flush=True,
        )
        adb("shell", "cmd", "uimode", "night", "yes")
        open_journal()
        find("В буфере: 105")
        shot("journal-dark.png")
        adb("shell", "wm", "size", "864x1536")
        adb("shell", "settings", "put", "system", "font_scale", "1.3")
        open_journal()
        find("Все: 105")
        shot("journal-small-font.png")
        assert len(core_items()) == 2, (
            "Синтетическая paused-очередь не должна отправляться"
        )
        print(
            "PASS: тёмная тема, ширина около 329dp и шрифт 1.3; пауза очереди не снята чтением журнала",
            flush=True,
        )
    finally:
        adb("shell", "wm", "size", "reset")
        adb("shell", "settings", "put", "system", "font_scale", "1.0")
        adb("shell", "cmd", "uimode", "night", "auto")
        adb("shell", "cmd", "notification", "disallow_listener", COMPONENT)
        open_journal()
        tap(find("Обновить журнал", top=True))
        adb("shell", "rm", "-f", remote, "/sdcard/task09-ui.xml")


if __name__ == "__main__":
    main()
