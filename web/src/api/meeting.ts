export interface MeetingPolicy {version:number;enabled:boolean;allowed_targets:string[];max_duration_seconds:number}
export interface MeetingView {event_id:string;event_revision:number;policy:MeetingPolicy;policy_scope:string;eligible:boolean;stale:boolean;starts_at:string;ends_at:string;status:string;targets:string[];approval_valid:boolean;started_targets:string[]}
export interface MeetingLease {entity_id:string;generation:string;state:string;reason:string|null;members:string[];event_id:number|null;updated_at:string}
export interface MeetingPage {status:string;policy:MeetingPolicy;plans:{event_id:string;event_revision:number;status:string;targets:string[];starts_at:string;ends_at:string}[];leases:MeetingLease[];history:{id:number;entity_id:string;state:string;reason:string|null;event_id:number|null;created_at:string}[]}
const object=(v:unknown):v is Record<string,unknown>=>v!==null && typeof v==='object' && !Array.isArray(v);
const entity=(v:unknown):v is string=>typeof v==='string' && /^switch\.[a-z0-9_]{1,248}$/.test(v);
const event=(v:unknown):v is string=>typeof v==='string' && /^cal_[a-f0-9]{32}$/.test(v);
const instant=(v:unknown):v is string=>typeof v==='string' && v.length<=40 && /Z$/.test(v) && Number.isFinite(Date.parse(v));
const targets=(v:unknown):v is string[]=>Array.isArray(v) && v.length<=5 && v.every(entity) && new Set(v).size===v.length;
const states=['waiting','applying','active','external','restoring','completed','unknown'];
export function knownMeetingPolicy(v:unknown):v is MeetingPolicy{return object(v) && v.version===1 && typeof v.enabled==='boolean' && targets(v.allowed_targets) && v.max_duration_seconds===28800;}
export function knownMeetingView(v:unknown):v is MeetingView {
  return object(v) && event(v.event_id) && Number.isSafeInteger(v.event_revision) && (v.event_revision as number)>0 && knownMeetingPolicy(v.policy)
    && typeof v.policy_scope==='string' && /^[a-f0-9]{64}$/.test(v.policy_scope) && typeof v.eligible==='boolean' && typeof v.stale==='boolean'
    && instant(v.starts_at) && instant(v.ends_at) && ['not_approved','approved','disabled','needs_review','finished'].includes(v.status as string)
    && targets(v.targets) && targets(v.started_targets) && typeof v.approval_valid==='boolean';
}
export function knownMeetingPage(v:unknown):v is MeetingPage {
  return object(v) && knownMeetingPolicy(v.policy) && Array.isArray(v.plans) && v.plans.length<=200 && v.plans.every(p=>object(p) && event(p.event_id) && Number.isSafeInteger(p.event_revision) && targets(p.targets) && instant(p.starts_at) && instant(p.ends_at) && typeof p.status==='string')
    && Array.isArray(v.leases) && v.leases.length<=100 && v.leases.every(l=>object(l) && entity(l.entity_id) && typeof l.generation==='string' && /^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(l.generation) && states.includes(l.state as string) && Array.isArray(l.members) && l.members.length<=200 && l.members.every(event) && instant(l.updated_at))
    && Array.isArray(v.history) && v.history.length<=50 && v.history.every(l=>object(l) && Number.isSafeInteger(l.id) && entity(l.entity_id) && states.includes(l.state as string) && instant(l.created_at));
}
export const meetingState:Record<string,string>={not_approved:'Не подтверждён',approved:'Согласие сохранено',disabled:'Выключен',needs_review:'Нужно новое подтверждение',finished:'Встреча завершена',waiting:'Ожидание устройства',applying:'Команда включения отправляется',active:'Включение наблюдалось',external:'Уже было включено — не выключаем',restoring:'Восстановление отправляется',completed:'Обработка завершена',unknown:'Результат неизвестен — проверьте устройство'};
export const meetingReason:Record<string,string>={RESTORE_OBSERVED:'Выключение наблюдалось',MANUAL_CHANGE_PRESERVED:'Ручное изменение сохранено',RESTORE_UNCONFIRMED:'Выключение не подтверждено',CORE_RESTARTED:'Core перезапустился во время команды',POLICY_REVOKED:'Разрешение на устройство отозвано'};
