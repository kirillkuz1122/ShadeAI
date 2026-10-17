import { useCallback, useEffect, useState } from "react";
import { api, type JournalEvent } from "../api/client";
import { useResource } from "../hooks/useResource";
import {
  ErrorNotice,
  Freshness,
  Loading,
  PAGE_SIZE,
  Pager,
  time,
} from "./common";

const types: Record<string, string> = {
  command_requested: "Отправляется",
  command_executed: "Принята HA",
  command_failed: "Ошибка",
  command_interrupted: "Исход неизвестен",
};
const codes: Record<string, string> = {
  HA_NOT_CONFIGURED: "HA не настроен",
  HA_AUTH_FAILED: "Токен HA не принят",
  HA_UNAVAILABLE: "HA недоступен",
  HA_TIMEOUT: "Время ожидания истекло",
  HA_SERVER_ERROR: "Ошибка сервера HA",
  HA_BAD_RESPONSE: "Неверный ответ HA",
  HA_COMMAND_REJECTED: "HA отклонил сервис",
  CORE_RESTARTED: "Core перезапущен до записи результата",
};
function outcome(event: JournalEvent) {
  const p = event.payload;
  const result =
    (
      {
        accepted: "Сервис принят. Физическое действие не подтверждено.",
        rejected: "HA отклонил запрос.",
        not_sent: "Команда не отправлена.",
        unknown:
          "Команда могла выполниться. Проверьте состояние перед повтором.",
      } as Record<string, string>
    )[p.outcome ?? ""] ?? "Исход не указан.";
  return `${p.error_code ? `${codes[p.error_code] ?? p.error_code}. ` : ""}${result}`;
}
export function Journal({ apiKey }: { apiKey: string }) {
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState("");
  const load = useCallback(
    (signal: AbortSignal) =>
      api.events({ apiKey, signal }, PAGE_SIZE, offset, filter),
    [apiKey, offset, filter],
  );
  const state = useResource(load);
  useEffect(() => {
    if (state.data && offset > 0 && offset >= state.data.total)
      setOffset(
        Math.max(0, Math.ceil(state.data.total / PAGE_SIZE) - 1) * PAGE_SIZE,
      );
  }, [state.data, offset]);
  return (
    <section className="panel history" aria-labelledby="journal-title">
      <header className="panel-heading">
        <div>
          <p className="eyebrow">Home Assistant</p>
          <h2 id="journal-title">
            Попытки команд{" "}
            {state.data && (
              <span className="count mono">{state.data.total}</span>
            )}
          </h2>
        </div>
        <button onClick={state.refresh} disabled={state.loading}>
          Обновить журнал
        </button>
      </header>
      <div className="journal-toolbar">
        <label htmlFor="event-filter">
          Результат{" "}
          <select
            id="event-filter"
            value={filter}
            onChange={(event) => {
              setFilter(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">Все попытки</option>
            {Object.entries(types).map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <Freshness
          updatedAt={state.updatedAt}
          loading={state.loading}
          stale={!!state.error}
        />
      </div>
      <p className="help journal-help">
        Принятие сервиса HA не подтверждает физическое действие. Команды с
        неизвестным исходом автоматически не повторяются.
      </p>
      {!!state.error && (
        <ErrorNotice error={state.error} retry={state.refresh} />
      )}
      {state.loading && !state.data && <Loading label="Загрузка журнала…" />}
      {state.data && (
        <>
          <div
            aria-busy={state.loading}
            className={state.error ? "stale-data" : ""}
          >
            {state.data.events.length === 0 ? (
              <div className="empty">
                <h3>
                  {filter ? "Таких попыток пока нет" : "Команд ещё не было"}
                </h3>
                <p>
                  {filter
                    ? "Выберите другой результат или обновите журнал."
                    : "Здесь появятся результаты команд, отправленных через Core."}
                </p>
              </div>
            ) : (
              <ol className="event-list">
                {state.data.events.map((event) => (
                  <li key={event.id}>
                    <div
                      className={`event-marker ${event.type === "command_executed" ? "event-marker--accepted" : ""}`}
                      aria-hidden="true"
                    />
                    <div className="event-body">
                      <div className="event-top">
                        <span
                          className={`event-status ${event.type === "command_failed" ? "event-status--error" : ""}`}
                        >
                          {types[event.type] ?? event.type}
                        </span>
                        <time dateTime={event.timestamp}>
                          {time(event.timestamp)}
                        </time>
                      </div>
                      <h3 className="mono">
                        {event.payload.entity_id ?? "Сущность неизвестна"}
                        <span>
                          {event.payload.service ?? "Сервис неизвестен"}
                        </span>
                      </h3>
                      <p>{outcome(event)}</p>
                      <span className="event-id mono">Попытка #{event.id}</span>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
          <Pager
            offset={offset}
            total={state.data.total}
            loading={state.loading}
            onChange={setOffset}
          />
        </>
      )}
    </section>
  );
}
