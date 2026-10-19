import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { api, type NotificationItem } from "../api/client";
import { ProcessingResult } from "./ProcessingResult";
import { categoryLabels, processingError } from "../api/processing";
import { useResource } from "../hooks/useResource";
import {
  ErrorNotice,
  Freshness,
  Loading,
  PAGE_SIZE,
  Pager,
  time,
} from "./common";

function appName(value: string) {
  return (
    (
      {
        "ru.ozon.app.android": "Ozon",
        "com.wildberries.ru": "Wildberries",
        "ru.yandex.taxi": "Яндекс Go",
      } as Record<string, string>
    )[value] ?? value
  );
}
const priorities: Record<string, string> = {
  min: "Минимальный",
  low: "Низкий",
  default: "Обычный",
  high: "Высокий",
  max: "Максимальный",
};

function processingLabel(n: NotificationItem, compact = false) {
  if (n.processing_status === "failed") return "Ошибка обработки";
  if (n.processing_status === "processing") return "Обрабатывается";
  if (n.processing_status === "processed" || n.status === "processed") {
    return n.processed_data?.processor === "diagnostic"
      ? "Проверка очереди завершена"
      : "Обработано";
  }
  return compact ? "Сохранено" : "Сохранено, ожидает обработки";
}


export function NotificationDetail({
  id,
  apiKey,
  close,
}: {
  id: number;
  apiKey: string;
  close: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const load = useCallback(
    (signal: AbortSignal) => api.notification({ apiKey, signal }, id),
    [apiKey, id],
  );
  const state = useResource(load, 5000);
  useEffect(() => {
    const node = dialog.current!;
    node.showModal();
    return () => node.close();
  }, []);
  const n = state.data;
  function keepFocus(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key !== "Tab") return;
    const buttons = dialog.current!.querySelectorAll<HTMLButtonElement>(
      "button:not(:disabled)",
    );
    const first = buttons[0],
      last = buttons[buttons.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }
  return (
    <dialog
      ref={dialog}
      onKeyDown={keepFocus}
      aria-labelledby="detail-title"
      onClose={() => {
        if (!dialog.current?.open) close();
      }}
      className="detail-dialog"
    >
      <header className="panel-heading">
        <div>
          <p className="eyebrow">Уведомление / {id}</p>
          <h2 id="detail-title">{n?.title || "Просмотр записи"}</h2>
        </div>
        <button
          autoFocus
          onClick={() => dialog.current?.close()}
          aria-label="Закрыть запись"
        >
          Закрыть
        </button>
      </header>
      {state.loading && !n && <Loading label="Загрузка уведомления…" />}
      {!!state.error && (
        <ErrorNotice error={state.error} retry={state.refresh} />
      )}
      {n && (
        <>
          <p className="notification-text">{n.text || "Текст отсутствует"}</p>
          <dl className="detail-fields">
            <div>
              <dt>Приложение</dt>
              <dd>
                {appName(n.app_name)}
                <small className="mono">{n.app_name}</small>
              </dd>
            </div>
            <div>
              <dt>Время события</dt>
              <dd>{time(n.timestamp)}</dd>
            </div>
            <div>
              <dt>Получено Core</dt>
              <dd>{time(n.created_at)}</dd>
            </div>
            <div>
              <dt>Идентификатор события</dt>
              <dd className="mono">{n.event_id ?? "Старая запись без UUID"}</dd>
            </div>
            <div>
              <dt>Приоритет</dt>
              <dd>{priorities[n.priority] ?? n.priority}</dd>
            </div>
            <div>
              <dt>Состояние</dt>
              <dd>
                {processingLabel(n)}
              </dd>
            </div>
            <div>
              <dt>Попыток обработки</dt>
              <dd>{n.processing_attempts ?? 0}</dd>
            </div>
            {n.processing_error_code && (
              <div>
                <dt>Причина</dt>
                <dd>{processingError(n.processing_error_code)}</dd>
              </div>
            )}
            <div>
              <dt>Категория</dt>
              <dd>{n.category && Object.hasOwn(categoryLabels, n.category) ? categoryLabels[n.category as keyof typeof categoryLabels] : "Не определена"}</dd>
            </div>
          </dl>
          <ProcessingResult data={n.processed_data} />
        </>
      )}
    </dialog>
  );
}

export function Notifications({ apiKey }: { apiKey: string }) {
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const load = useCallback(
    (signal: AbortSignal) =>
      api.notifications({ apiKey, signal }, PAGE_SIZE, offset),
    [apiKey, offset],
  );
  const state = useResource(load);
  useEffect(() => {
    if (state.data && offset > 0 && offset >= state.data.total)
      setOffset(
        Math.max(0, Math.ceil(state.data.total / PAGE_SIZE) - 1) * PAGE_SIZE,
      );
  }, [state.data, offset]);
  return (
    <section className="panel history" aria-labelledby="history-title">
      <header className="panel-heading">
        <div>
          <p className="eyebrow">Входящие события</p>
          <h2 id="history-title">
            История уведомлений{" "}
            {state.data && (
              <span className="count mono">{state.data.total}</span>
            )}
          </h2>
        </div>
        <button onClick={state.refresh} disabled={state.loading}>
          Обновить историю
        </button>
      </header>
      <div className="list-meta">
        <span>Последние события — сверху</span>
        <Freshness
          updatedAt={state.updatedAt}
          loading={state.loading}
          stale={!!state.error}
        />
      </div>
      {!!state.error && (
        <ErrorNotice error={state.error} retry={state.refresh} />
      )}
      {state.loading && !state.data && <Loading />}
      {state.data && (
        <>
          <div
            aria-busy={state.loading}
            className={state.error ? "stale-data" : ""}
          >
            {state.data.items.length === 0 ? (
              <div className="empty">
                <h3>Здесь пока тихо</h3>
                <p>
                  Допустимые уведомления появятся после доставки в Core.
                  <br />
                  Подключение Android ещё настраивается отдельно.
                </p>
              </div>
            ) : (
              <ul className="notification-list">
                {state.data.items.map((n) => (
                  <li key={n.id}>
                    <button
                      className="notification-row"
                      onClick={() => setSelected(n.id)}
                      aria-label={`Открыть уведомление: ${n.title || "Без заголовка"}`}
                    >
                      <span className="app-symbol" aria-hidden="true">
                        {appName(n.app_name).slice(0, 1)}
                      </span>
                      <span className="notification-main">
                        <span className="notification-top">
                          <strong>{n.title || "Без заголовка"}</strong>
                          <time dateTime={n.timestamp}>
                            {time(n.timestamp)}
                          </time>
                        </span>
                        <span className="notification-preview">{n.text}</span>
                        <span className="notification-bottom">
                          <span>{appName(n.app_name)}</span>
                          <span>
                            {processingLabel(n, true)}
                            {n.category && Object.hasOwn(categoryLabels, n.category) ? ` · ${categoryLabels[n.category as keyof typeof categoryLabels]}` : ""}
                          </span>
                        </span>
                      </span>
                      <span className="row-arrow" aria-hidden="true">
                        ↗
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
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
      {selected !== null && (
        <NotificationDetail
          id={selected}
          apiKey={apiKey}
          close={() => setSelected(null)}
        />
      )}
    </section>
  );
}
