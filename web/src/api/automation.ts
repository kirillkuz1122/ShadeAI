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
  approval_scope?:string;
  execution_policy?: {version:1;enabled:boolean;home_presence_entity:string|null;cancel_seconds:number;cooldown_seconds:number;max_event_age_seconds:number;pair_window_seconds:number};
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
  if(value.approval_scope!==undefined && (typeof value.approval_scope!=="string" || !/^[0-9a-f]{64}$/.test(value.approval_scope))) return false;
  const policy=value.execution_policy;
  if (policy === undefined && value.executor_status!=="not_implemented") return false;
  if (policy !== undefined && (!object(policy) || policy.version!==1 || typeof policy.enabled!=="boolean"
    || !(policy.home_presence_entity===null || typeof policy.home_presence_entity==="string" && /^binary_sensor\.[a-z0-9_]+$/.test(policy.home_presence_entity))
    || !Number.isInteger(policy.cancel_seconds) || (policy.cancel_seconds as number)<10 || (policy.cancel_seconds as number)>120
    || !Number.isInteger(policy.cooldown_seconds) || (policy.cooldown_seconds as number)<300 || (policy.cooldown_seconds as number)>86400
    || policy.max_event_age_seconds!==300 || policy.pair_window_seconds!==90)) return false;
  if (object(policy) && policy.enabled===true && value.approval_scope===undefined) return false;
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

export type RunState="pending"|"cancelled"|"dispatching"|"succeeded"|"failed"|"unknown"|"skipped";
export interface AutomationRun {id:number;rule_id:string;state:RunState;reason:string;target_entity:string;service:"turn_on"|"turn_off";created_at:string;due_at:string;started_at:string|null;finished_at:string|null;event_id:number|null;cancellable:boolean}
export interface RunPage {status:string;runs:AutomationRun[]}
export const runStates:Record<RunState,string>={pending:"Ожидает отправки",cancelled:"Отменено",dispatching:"Команда отправляется",succeeded:"Команда принята HA",failed:"Ошибка",unknown:"Результат неизвестен",skipped:"Пропущено"};
export const runReasons:Record<string,string>={WAITING_CANCEL_WINDOW:"Два источника подтвердили переход. Действует время для отмены.",CORE_RESTARTED:"Core перезапущен, повтор не выполняется.",USER_CANCELLED:"Отменено пользователем.",RULE_DISABLED:"Правило отклонено или выключено.",APPROVAL_CHANGED:"Согласие или условия изменились.",PRESENCE_UNCONFIRMED:"Присутствие больше не подтверждено.",COOLDOWN:"Защита от частых действий для этого света.",COMMAND_IN_FLIGHT:"Отправка уже началась.",HA_ACCEPTED:"HA принял команду.",AUDIT_UNAVAILABLE:"Журнал недоступен, команда не отправлена.",AUDIT_FINALIZATION_FAILED:"Итог не удалось записать. Повтора нет.",HA_UNCONFIRMED:"HA не подтвердил результат. Повтора нет.",HA_FAILED:"HA отклонил команду или недоступен.",COMMAND_UNCONFIRMED:"Отправка не подтверждена. Повтора нет."};
export function knownRunPage(value:unknown):value is RunPage {
  return object(value) && Array.isArray(value.runs) && value.runs.length<=20 && value.runs.every(row=>object(row)
    && Number.isSafeInteger(row.id) && (row.id as number)>0 && typeof row.rule_id==="string" && /^aut_[0-9a-f]{32}$/.test(row.rule_id)
    && typeof row.state==="string" && Object.hasOwn(runStates,row.state) && typeof row.reason==="string" && row.reason.length<=64
    && allowedLight(row.target_entity) && ["turn_on","turn_off"].includes(row.service as string)
    && typeof row.created_at==="string" && typeof row.due_at==="string"
    && typeof row.cancellable==="boolean" && row.cancellable===(row.state==="pending"));
}
