import { useCallback, useState, type FormEvent } from "react";
import { api, getApiKey, setApiKey } from "./api/client";
import { useResource } from "./hooks/useResource";
import { HealthPanel } from "./components/HealthPanel";
import { Notifications } from "./components/Notifications";
import { Automations } from "./components/Automations";
import {Calendar} from "./components/Calendar";
import { Journal } from "./components/Journal";

export default function App() {
  const [credential, setCredential] = useState(() => ({
    key: getApiKey(),
    version: 0,
  }));
  const [draft, setDraft] = useState(credential.key);
  const [saved, setSaved] = useState("");
  const [connectionOpen, setConnectionOpen] = useState(!credential.key);
  const [section, setSection] = useState<"notifications" | "journal" | "automations" | "calendar">(
    "notifications",
  );
  const loadHealth = useCallback(
    (signal: AbortSignal) => api.health(signal),
    [],
  );
  const health = useResource(loadHealth);

  function save(event: FormEvent) {
    event.preventDefault();
    const key = draft.trim();
    const persisted = setApiKey(key);
    setDraft(key);
    setCredential((old) => ({ key, version: old.version + 1 }));
    setSaved(
      persisted
        ? key
          ? "Ключ сохранён в этом браузере. Проверяем доступ…"
          : "Ключ удалён из браузера."
        : "Браузер запретил сохранение. Ключ действует до закрытия страницы.",
    );
    health.refresh();
  }

  return (
    <div className="shell">
      <a className="skip-link" href="#content">
        К содержимому
      </a>
      <aside className="sidebar" aria-label="Навигация">
        <a className="brand" href="#content" aria-label="Shade AI — главная">
          <span className="brand-mark" aria-hidden="true">
            S<span />
          </span>
          <span>
            shade<span className="brand-ai">ai</span>
          </span>
        </a>
        <p className="eyebrow sidebar-caption">Локальный ассистент</p>
        <nav className="sections" aria-label="Разделы">
          <button
            aria-current={section === "notifications" ? "page" : undefined}
            onClick={() => setSection("notifications")}
          >
            <span aria-hidden="true">01</span> Уведомления
          </button>
          <button
            aria-current={section === "journal" ? "page" : undefined}
            onClick={() => setSection("journal")}
          >
            <span aria-hidden="true">02</span> Журнал команд
          </button>
          <button aria-current={section === "automations" ? "page" : undefined} onClick={()=>setSection("automations")}>
            <span aria-hidden="true">03</span> Сценарии и подсказки
          </button>
          <button aria-current={section==="calendar"?"page":undefined} onClick={()=>setSection("calendar")}><span aria-hidden="true">04</span> Календарь</button>
        </nav>
        <div className="local-note">
          <svg
            aria-hidden="true"
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.75"
          >
            <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z" />
            <path d="m8 12 3 3 5-6" />
          </svg>
          <div>
            <strong>В пределах дома</strong>
            <p>Данные остаются в вашей локальной сети.</p>
          </div>
        </div>
        <div className="sidebar-bottom">
          <span className="mono">SHADE CORE</span>
          <span>v0.1 · разработка</span>
        </div>
      </aside>

      <main id="content" className="workspace" tabIndex={-1}>
        <header className="page-header">
          <div>
            <p className="eyebrow">Домашний контур / Обзор</p>
            <h1>
              {{notifications:"Уведомления",journal:"Журнал команд",automations:"Сценарии и подсказки",calendar:"Календарь"}[section]}
            </h1>
            <p className="intro">
              {section === "notifications"
                ? "История событий с ваших устройств."
                : section==="calendar"?"Расписание из вашего локального календаря.":section==="automations"?"Предложения, ваши решения и исполнение сценариев.":"Что Core отправил в Home Assistant и какой ответ получил."}
            </p>
          </div>
          <span className="local-badge">
            <i />
            Zero Cloud
          </span>
        </header>
        <HealthPanel resource={health} />
        <details
          className="connection"
          open={connectionOpen}
          onToggle={(event) => setConnectionOpen(event.currentTarget.open)}
        >
          <summary>
            Подключение к Core{" "}
            <span>{credential.key ? "Ключ задан" : "Требуется ключ"}</span>
          </summary>
          <form onSubmit={save} className="connection-form">
            <div>
              <label htmlFor="api-key">API-ключ Shade</label>
              <input
                id="api-key"
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                aria-describedby="key-help"
                placeholder="Введите ключ Core"
              />
            </div>
            <button className="primary" type="submit">
              Сохранить ключ
            </button>
            <button
              type="button"
              onClick={() => {
                const persisted = setApiKey("");
                setDraft("");
                setCredential((old) => ({ key: "", version: old.version + 1 }));
                setSaved(
                  persisted
                    ? "Ключ удалён. История скрыта."
                    : "История скрыта. Браузер запретил удаление сохранённого ключа.",
                );
              }}
            >
              Удалить ключ
            </button>
            <p id="key-help" className="help">
              Ключ из локального файла настроек Core. Сохраняется в этом
              браузере; на общем компьютере удалите его после работы.
            </p>
            <p className="save-status" role="status">
              {saved}
            </p>
          </form>
        </details>
        {!credential.key ? (
          <section className="panel empty welcome">
            <p className="eyebrow">Начало работы</p>
            <h2>Подключите свою историю</h2>
            <p>
              Укажите ключ в настройках подключения выше.
              <br />
              Состояние сервера доступно без ключа.
            </p>
            <button onClick={() => document.getElementById("api-key")?.focus()}>
              Ввести ключ
            </button>
          </section>
        ) : (
          <div key={credential.version}>
            {section === "notifications" ? (
              <Notifications apiKey={credential.key} />
            ) : section === "calendar" ? (
              <Calendar key={credential.key} apiKey={credential.key}/>
            ) : section === "automations" ? (
              <Automations apiKey={credential.key} />
            ) : (
              <Journal apiKey={credential.key} />
            )}
          </div>
        )}
        <footer className="workspace-footer">
          <span>{section==="calendar"?"Кэш каждые 30 секунд · пояс календаря":"Обновление каждые 10 секунд · время вашего браузера"}</span>
          <span>Мой дом — мои данные.</span>
        </footer>
      </main>
    </div>
  );
}
