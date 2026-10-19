import { ApiError, ProtocolError } from "../api/client";

export const PAGE_SIZE = 20;
export function time(value: string | Date) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Время неизвестно"
    : date.toLocaleString("ru-RU", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
}
export function errorMessage(error: unknown): string {
  if (error instanceof ProtocolError) return "Формат ответа Core не поддерживается. Обновите клиент.";
  if (error instanceof ApiError) {
    if (error.status === 401)
      return "Ключ не принят. Проверьте его в настройках подключения.";
    if (error.status === 404)
      return "Запись уже удалена или срок её хранения истёк.";
    if (error.status === 503)
      return "Сервис временно недоступен. Проверьте блок состояния Core.";
    if (error.status === 502 || error.status === 504)
      return "Сервер не ответил вовремя. Соединение будет проверено снова.";
    return `Не удалось получить данные (HTTP ${error.status}).`;
  }
  if (error instanceof Error && error.name === "AbortError")
    return "Время ожидания истекло. Повторим проверку соединения.";
  return "Нет связи с Core. Проверьте локальную сеть и доступность сервера.";
}
export function ErrorNotice({
  error,
  retry,
}: {
  error: unknown;
  retry: () => void;
}) {
  return (
    <div className="notice notice--error" role="alert">
      <span>{errorMessage(error)}</span>
      <button className="text-button" onClick={retry}>
        Повторить
      </button>
    </div>
  );
}
export function Pager({
  offset,
  total,
  loading,
  onChange,
}: {
  offset: number;
  total: number;
  loading: boolean;
  onChange: (offset: number) => void;
}) {
  return (
    <nav className="pagination" aria-label="Страницы списка">
      <span className="mono">
        {total === 0
          ? "0 записей"
          : `${Math.min(offset + 1, total)}–${Math.min(offset + PAGE_SIZE, total)} из ${total}`}
      </span>
      <div>
        <button
          disabled={offset === 0 || loading}
          onClick={() => onChange(Math.max(0, offset - PAGE_SIZE))}
        >
          Назад
        </button>
        <button
          disabled={offset + PAGE_SIZE >= total || loading}
          onClick={() => onChange(offset + PAGE_SIZE)}
        >
          Далее
        </button>
      </div>
    </nav>
  );
}
export function Loading({ label = "Загрузка записей…" }: { label?: string }) {
  return (
    <div className="empty" role="status">
      <span className="loading-line" />
      {label}
    </div>
  );
}
export function Freshness({
  updatedAt,
  loading,
  stale,
}: {
  updatedAt: Date | null;
  loading: boolean;
  stale: boolean;
}) {
  return (
    <span className="freshness">
      {loading
        ? "Обновление…"
        : updatedAt
          ? `${stale ? "Последние данные" : "Обновлено"} ${time(updatedAt)}`
          : "Ожидание данных"}
    </span>
  );
}
