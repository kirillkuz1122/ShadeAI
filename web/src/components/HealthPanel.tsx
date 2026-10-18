import { type Health } from "../api/client";
import { type useResource } from "../hooks/useResource";
import { ErrorNotice, Freshness } from "./common";

const haMessages: Record<string, string> = {
  HA_NOT_CONFIGURED: "Не настроен",
  HA_AUTH_FAILED: "Токен HA не принят",
  HA_TIMEOUT: "Таймаут",
  HA_UNAVAILABLE: "Нет соединения",
  HA_SERVER_ERROR: "Ошибка HA",
  HA_BAD_RESPONSE: "Неверный ответ HA",
};
export function HealthPanel({
  resource: state,
}: {
  resource: ReturnType<typeof useResource<Health>>;
}) {
  const h = state.data;
  const stale = !!state.error;
  return (
    <section className="health panel" aria-labelledby="health-title">
      <div className="panel-heading">
        <h2 id="health-title">
          <span
            className={`status-dot ${!h || stale ? "status-dot--off" : h.status === "ok" ? "status-dot--on" : "status-dot--warning"}`}
          />
          Состояние Core
        </h2>
        <button
          className="text-button"
          onClick={state.refresh}
          disabled={state.loading}
        >
          Проверить связь
        </button>
      </div>
      {!!state.error && (
        <ErrorNotice error={state.error} retry={state.refresh} />
      )}
      <div className="health-grid" aria-busy={state.loading}>
        <div>
          <span>Сервер</span>
          <strong>
            {stale
              ? "Нет актуальных данных"
              : h
                ? h.status === "ok"
                  ? "На связи"
                  : h.status === "degraded"
                    ? "Частично доступен"
                    : "Ошибка"
                : "Проверка…"}
          </strong>
          <small>
            {h && !stale
              ? `В работе ${Math.floor(h.uptime / 60)} мин`
              : "Проверяем локальный Core"}
          </small>
        </div>
        <div>
          <span>База данных</span>
          <strong>
            {h ? (h.db_connected ? "Доступна" : "Недоступна") : "—"}
          </strong>
          <small>
            {h
              ? h.db_size === "unknown"
                ? "Размер неизвестен"
                : `${h.db_size} · SQLite + WAL`
              : "Ожидание ответа"}
          </small>
        </div>
        <div>
          <span>Home Assistant</span>
          <strong>
            {h
              ? h.ha_connected
                ? "Подключён"
                : (haMessages[h.ha_status] ?? "Недоступен")
              : "—"}
          </strong>
          <small>
            {h && !h.ha_connected
              ? "История уведомлений доступна"
              : "Локальное соединение"}
          </small>
        </div>
        <div>
          <span>AI и привычки</span>
          <strong>
            {h?.llm_status === "ready"
              ? "Локальная модель готова"
              : h?.llm_status === "loading"
                ? "Загрузка модели"
                : h && h.llm_status !== "not_loaded"
                  ? "Модель недоступна"
                  : "Ещё не подключены"}
          </strong>
          <small>
            {h?.llm_status === "ready"
              ? "Движок готов; анализ и привычки ещё не настроены"
              : "Анализ уведомлений не выполняется"}
          </small>
        </div>
      </div>
      <Freshness
        updatedAt={state.updatedAt}
        loading={state.loading}
        stale={stale}
      />
    </section>
  );
}
