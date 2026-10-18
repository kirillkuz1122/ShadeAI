const intents = {
  delivery: "delivery_event", transport: "transport_event", calendar: "calendar_event",
  reminder: "reminder", noise: "none",
} as const;
export type Category = keyof typeof intents;
export const categoryLabels: Record<Category, string> = {
  delivery: "Доставка", transport: "Поездка", calendar: "Встреча",
  reminder: "Напоминание", noise: "Не требует внимания",
};
export const priorityLabels: Record<string, string> = {
  low: "Низкий", default: "Обычный", high: "Высокий",
};
export interface Extraction {
  category: Category;
  priority: "low" | "default" | "high";
  entities: { subject: string | null; location: string | null; service: string | null };
  time: {
    source: string | null; timezone: string; at: string | null; date: string | null;
    resolution: "absent" | "exact" | "date_only" | "unresolved";
  };
}
export type Processing = { kind: "none" } | { kind: "diagnostic" } | { kind: "unsupported" }
  | { kind: "llm"; value: Extraction };
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown, max: number): value is string =>
  typeof value === "string" && value.trim().length > 0 && value.length <= max
  && !/[\u0000-\u001f\u007f]/.test(value);
const optional = (value: unknown, max: number): value is string | null =>
  value === null || text(value, max);
function validDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}
export function readProcessing(input: unknown): Processing {
  if (input == null) return { kind: "none" };
  const unsupported: Processing = { kind: "unsupported" };
  if (!object(input)) return unsupported;
  if (input.processor === "diagnostic" && input.llm === false) return { kind: "diagnostic" };
  if (input.processor !== "llm" || input.llm !== true || input.schema_version !== 1
    || input.action_authorized !== false || typeof input.category !== "string"
    || !Object.hasOwn(intents, input.category)
    || input.intent !== intents[input.category as Category]
    || !["low", "default", "high"].includes(input.priority as string)) return unsupported;
  const { entities, time } = input;
  if (!object(entities) || !object(time)
    || !optional(entities.subject, 160) || !optional(entities.location, 200)
    || !optional(entities.service, 80) || !optional(time.source, 128)
    || !text(time.timezone, 64)
    || !["absent", "exact", "date_only", "unresolved"].includes(time.resolution as string)) return unsupported;
  try { new Intl.DateTimeFormat("ru-RU", { timeZone: time.timezone }); }
  catch { return unsupported; }
  if ((time.resolution === "absent") !== (time.source === null)) return unsupported;
  if (time.resolution === "exact") {
    if (typeof time.at !== "string"
      || !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?Z$/.test(time.at)
      || !validDate(time.at.slice(0, 10)) || !Number.isFinite(Date.parse(time.at))
      || time.date !== null) return unsupported;
  } else if (time.resolution === "date_only") {
    if (!validDate(time.date) || time.at !== null) return unsupported;
  } else if (time.at !== null || time.date !== null) return unsupported;
  if (input.category === "noise" && (input.priority !== "low"
    || Object.values(entities).some(value => value !== null) || time.resolution !== "absent")) return unsupported;
  // Копируем только известные поля: произвольные поля ответа не попадают в UI.
  return { kind: "llm", value: {
    category: input.category as Category, priority: input.priority as Extraction["priority"],
    entities: { subject: entities.subject, location: entities.location, service: entities.service },
    time: { source: time.source, timezone: time.timezone, at: time.at as string | null,
      date: time.date as string | null, resolution: time.resolution as Extraction["time"]["resolution"] },
  } };
}
export function extractionTime(value: Extraction["time"]): string {
  if (value.resolution === "absent") return "Время не указано";
  if (value.resolution === "unresolved") return "Точное время не определено";
  if (value.resolution === "date_only") {
    const [year, month, day] = value.date!.split("-");
    return `${day}.${month}.${year} · время не указано`;
  }
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: value.timezone, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).format(new Date(value.at!));
}
const errors: Record<string, string> = {
  PROCESSOR_ERROR: "Обработчик завершился с ошибкой",
  PROCESSOR_TIMEOUT: "Превышено время обработки",
  INVALID_RESULT: "Обработчик вернул неверный результат",
  INVALID_NOTIFICATION: "Сохранённая запись не прошла проверку",
  PROCESSING_INTERRUPTED: "Предыдущая попытка прервана; запись ожидает обработки",
  LLM_BAD_RESPONSE: "Модель вернула неподтверждённые или неполные сведения",
  LLM_TIMEOUT: "Модель не успела обработать уведомление",
  LLM_CONTEXT_EXCEEDED: "Текст не помещается в контекст модели",
  LLM_PROCESS_EXITED: "Процесс модели завершился во время обработки",
  LLM_INFERENCE_FAILED: "Не удалось выполнить локальный разбор",
  LLM_CANCELLED: "Разбор был прерван",
};
export function processingError(code: string): string {
  return Object.hasOwn(errors, code) ? errors[code] : "Не удалось обработать запись";
}
