import { categoryLabels, extractionTime, priorityLabels, readProcessing } from "../api/processing";

export function ProcessingResult({ data }: { data: unknown }) {
  const result = readProcessing(data);
  if (result.kind === "none") return <p className="help">Результат разбора ещё не получен.</p>;
  if (result.kind === "diagnostic") return <p className="help">Проверен конвейер очереди. Анализ текста и LLM не выполнялись.</p>;
  if (result.kind === "unsupported") return <p className="notice" role="status">Формат результата не поддерживается. Обновите клиент или проверьте версию Core.</p>;
  const { category, priority, entities, time } = result.value;
  return <section aria-labelledby="extraction-title">
    <h3 id="extraction-title">Локальный разбор</h3>
    <dl className="detail-fields">
      <div><dt>Категория разбора</dt><dd>{categoryLabels[category]}</dd></div>
      <div><dt>Приоритет разбора</dt><dd>{priorityLabels[priority]}</dd></div>
      <div><dt>Событие / дело</dt><dd>{entities.subject ?? "Не указано"}</dd></div>
      <div><dt>Место</dt><dd>{entities.location ?? "Не указано"}</dd></div>
      <div><dt>Сервис</dt><dd>{entities.service ?? "Не указан"}</dd></div>
      <div><dt>Распознанное время</dt><dd>{extractionTime(time)}</dd></div>
      {time.source && <div><dt>Время в тексте</dt><dd>{time.source}</dd></div>}
      <div><dt>Часовой пояс разбора</dt><dd>{time.timezone}</dd></div>
    </dl>
    <p className="help">Модель может ошибаться. Результат описывает уведомление и не разрешает управление устройствами.</p>
  </section>;
}
