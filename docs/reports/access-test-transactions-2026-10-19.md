# Тестовые транзакции доступа — 19 октября

Полный регресс Python3.11/network none при подготовке TASK-08 дал479PASS/1FAIL:
`test_only_fresh_canonical_delivery_can_receive_access[future]` падал
`database is locked` при ручной мутации SQLite после session.get. Фоновое
обслуживание может записать БД между deferred SELECT и UPDATE теста.

В четырёх тестовых writer-транзакциях BEGIN IMMEDIATE запрашивается до чтения.
Производственный AccessService уже использует этот порядок; он не менялся.
Проверки отказа stale/private/изменённого/будущего источника сохраняются.

После исправления:52focused Access/dashboard/backup на Python3.14 PASS, полный
480Core на Python3.11/network none PASS.480 включает17новых тестов08 из текущего
ещё не закоммиченного среза; не выдавать эту цифру за состав старого коммита26.
Ruff PASS. Это изоляция тестов, не аппаратная проверка замка.
