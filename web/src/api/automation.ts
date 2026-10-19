export type RuleStatus = "pending" | "accepted" | "rejected" | "disabled" | "needs_review";
export interface AutomationRule {
  id: string; source_habit_id: string; name: string; status: RuleStatus; version: number;
  trigger: {type: "presence_transition"; kind: "arrival_home" | "departure_home";
    entity_id: string; from_state: "on" | "off"; to_state: "on" | "off";
    day_group: "weekdays" | "weekends"; timezone: string;
    window_start: string; window_end: string; wraps_midnight: boolean};
  action: {entity_id: string; service: "turn_on" | "turn_off"; params: Record<string, never>} | null;
  evidence: {support_days: number; eligible_days: number; dispersion_minutes: number};
  confidence: number; source_current: boolean; approval_valid: boolean; enabled: boolean;
  executable: boolean; executor_status: string; created_at: string; updated_at: string;
}
export interface AutomationPage {
  automations: AutomationRule[]; total: number; allowed_targets: string[];
  status: string; executor_status: string;
}
export interface AutomationDetail extends AutomationRule {
  history: {id: number; decision: string; version: number; target_entity: string | null; created_at: string}[];
}
export interface Hint { id: number; kind: string; notification_id: number; created_at: string }
export interface HintPage {feed_id: string | null; latest_id: number; next_id: number; hints: Hint[]}
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
export const allowedLight = (value: unknown): value is string =>
  typeof value === "string" && value.length <= 255 && /^light\.[a-z0-9_]+$/.test(value);
export function knownRule(value: unknown): value is AutomationRule {
  if (!object(value) || typeof value.id !== "string" || !/^aut_[0-9a-f]{32}$/.test(value.id)
    || typeof value.name !== "string" || (!value.name.trim() || value.name.length > 200)
    || !Number.isInteger(value.version) || (value.version as number) < 1
    || !["pending","accepted","rejected","disabled","needs_review"].includes(value.status as string)
    || typeof value.confidence !== "number" || !Number.isFinite(value.confidence)
    || value.confidence < 0 || value.confidence > 1
    || ["source_current","approval_valid","enabled","executable"].some(k => typeof value[k] !== "boolean")) return false;
  const t=value.trigger, e=value.evidence;
  if (!object(t) || t.type !== "presence_transition" || !["arrival_home","departure_home"].includes(t.kind as string)
    || typeof t.entity_id !== "string" || !/^binary_sensor\.[a-z0-9_]+$/.test(t.entity_id)
    || !["weekdays","weekends"].includes(t.day_group as string) || typeof t.timezone !== "string"
    || t.from_state !== (t.kind === "arrival_home" ? "off" : "on")
    || t.to_state !== (t.kind === "arrival_home" ? "on" : "off")
    || [t.window_start,t.window_end].some(v => typeof v !== "string" || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(v))
    || typeof t.wraps_midnight !== "boolean" || !object(e)
    || !Number.isInteger(e.support_days) || !Number.isInteger(e.eligible_days)
    || (e.support_days as number) < 0 || (e.eligible_days as number) < 1 || (e.eligible_days as number) > 30
    || (e.support_days as number) > (e.eligible_days as number)
    || typeof e.dispersion_minutes !== "number" || !Number.isFinite(e.dispersion_minutes)
    || e.dispersion_minutes < 0 || e.dispersion_minutes > 45) return false;
  try { new Intl.DateTimeFormat("ru-RU", {timeZone:t.timezone}); } catch { return false; }
  if (value.action !== null) {
    const a=value.action;
    if (!object(a) || !allowedLight(a.entity_id) || !object(a.params) || Object.keys(a.params).length
      || a.service !== (t.kind === "arrival_home" ? "turn_on" : "turn_off")) return false;
  }
  return true;
}
export const ruleLabels: Record<RuleStatus, string> = {
  pending:"Предложение", accepted:"Принято", rejected:"Отклонено", disabled:"Выключено", needs_review:"Требуется новое решение",
};
export const decisionLabels: Record<string, string> = {
  suggested:"Предложено", accept:"Принято пользователем", reject:"Отклонено пользователем", disable:"Выключено пользователем",
  source_changed:"Условия изменились", evidence_updated:"Обновлена статистика",
  source_unavailable:"Источник недоступен", approval_invalidated:"Нужно новое подтверждение",
};

export function knownAutomationPage(value: unknown): value is AutomationPage {
  return object(value) && Array.isArray(value.automations) && value.automations.length <= 20
    && Number.isSafeInteger(value.total) && (value.total as number) >= 0
    && Array.isArray(value.allowed_targets) && value.allowed_targets.length <= 20
    && value.allowed_targets.every(allowedLight);
}
export function knownHintPage(value: unknown): value is HintPage {
  return object(value) && (value.feed_id === null || (typeof value.feed_id === "string"
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value.feed_id)))
    && Number.isSafeInteger(value.latest_id) && (value.latest_id as number) >= 0
    && Number.isSafeInteger(value.next_id) && (value.next_id as number) >= 0
    && Array.isArray(value.hints) && value.hints.length <= 20
    && value.hints.every(item => object(item) && Number.isSafeInteger(item.id) && (item.id as number)>0
      && typeof item.kind === "string" && item.kind.length<=64
      && Number.isSafeInteger(item.notification_id) && (item.notification_id as number)>0
      && typeof item.created_at === "string");
}
