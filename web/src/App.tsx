import { useCallback, useEffect, useState } from "react";
import { api, getApiKey, setApiKey, type Health, type NotificationsResponse } from "./api/client";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [notifications, setNotifications] = useState<NotificationsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [apiKey, setKey] = useState(getApiKey());

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [h, n] = await Promise.all([api.health(), api.notifications(50)]);
      setHealth(h);
      setNotifications(n);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка запроса");
      setHealth(null);
      setNotifications(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
  }, [refresh]);

  return (
    <div className="app">
      <header className="header">
        <div className="header__logo">S</div>
        <h1>Shade AI — дашборд</h1>
      </header>

      <div className="card">
        <h2>Подключение</h2>
        <div className="settings-row">
          <input
            type="password"
            placeholder="Shade API ключ"
            value={apiKey}
            onChange={(e) => setKey(e.target.value)}
          />
          <button
            onClick={() => {
              setApiKey(apiKey.trim());
              void refresh();
            }}
          >
            Сохранить
          </button>
          <button onClick={() => void refresh()}>Обновить</button>
        </div>
        {error && <p className="badge">Нет связи с Shade Core: {error}</p>}
      </div>

      {health && (
        <div className="card">
          <h2>Состояние сервера</h2>
          <div className="stat">
            <span>Статус</span>
            <span className="stat--ok">{health.status}</span>
          </div>
          <div className="stat">
            <span>Uptime</span>
            <span>{Math.floor(health.uptime / 60)} мин</span>
          </div>
          <div className="stat">
            <span>Home Assistant</span>
            <span>{health.ha_connected ? "подключен" : "нет связи"}</span>
          </div>
          <div className="stat">
            <span>LLM</span>
            <span>{health.llm_status}</span>
          </div>
          <div className="stat">
            <span>Размер БД</span>
            <span>{health.db_size}</span>
          </div>
        </div>
      )}

      {notifications && (
        <div className="card">
          <h2>Уведомления ({notifications.total})</h2>
          {notifications.items.length === 0 ? (
            <p className="muted">Пока пусто. Отправь тестовое уведомление в /api/v1/notifications.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Время</th>
                  <th>Приложение</th>
                  <th>Заголовок</th>
                  <th>Текст</th>
                  <th>Категория</th>
                </tr>
              </thead>
              <tbody>
                {notifications.items.map((n) => (
                  <tr key={n.id}>
                    <td className="muted">{new Date(n.timestamp).toLocaleString("ru-RU")}</td>
                    <td>{n.app_name}</td>
                    <td>{n.title}</td>
                    <td>{n.text}</td>
                    <td>{n.category ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
