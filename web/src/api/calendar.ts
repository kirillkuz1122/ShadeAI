export interface CalendarEvent {id:string;summary:string;location:string|null;starts_at:string;ends_at:string;start_date:string|null;end_date:string|null;all_day:boolean;status:"confirmed"|"tentative"|"cancelled"|"removed";busy:boolean;revision:number;updated_at:string}
export interface CalendarPage {status:string;configured:boolean;stale:boolean;timezone:string;last_success:string|null;window_start:string|null;window_end:string|null;error_code:string|null;events:CalendarEvent[];total:number}
const object=(v:unknown):v is Record<string,unknown>=>v!==null && typeof v==="object" && !Array.isArray(v);
const instant=(v:unknown):v is string=>typeof v==="string" && v.length<=40 && /^\d{4}-\d{2}-\d{2}T.*Z$/.test(v) && Number.isFinite(Date.parse(v));
const date=(v:unknown):v is string=>typeof v==="string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0,10)===v;
export function knownCalendarPage(v:unknown):v is CalendarPage {
  if(!object(v) || typeof v.configured!=="boolean" || typeof v.stale!=="boolean" || typeof v.timezone!=="string"
    || !(v.last_success===null || instant(v.last_success))
    || !Number.isSafeInteger(v.total) || (v.total as number)<0 || (v.total as number)>1000 || !Array.isArray(v.events) || v.events.length>50)return false;
  try{new Intl.DateTimeFormat("ru-RU",{timeZone:v.timezone});}catch{return false;}
  return v.events.every(e=>object(e) && typeof e.id==="string" && /^cal_[0-9a-f]{32}$/.test(e.id)
    && typeof e.summary==="string" && e.summary.length<=200 && (e.location===null || typeof e.location==="string" && e.location.length<=255)
    && instant(e.starts_at) && instant(e.ends_at) && Date.parse(e.ends_at)>=Date.parse(e.starts_at)
    && typeof e.all_day==="boolean" && typeof e.busy==="boolean" && ["confirmed","tentative","cancelled","removed"].includes(e.status as string)
    && Number.isSafeInteger(e.revision) && (e.revision as number)>0
    && (e.all_day ? date(e.start_date) && date(e.end_date) && e.end_date>e.start_date : e.start_date===null && e.end_date===null));
}
export function calendarTime(e:CalendarEvent,zone:string):string {
  if(e.all_day){
    const format=new Intl.DateTimeFormat("ru-RU",{timeZone:"UTC",day:"numeric",month:"long",year:"numeric"});
    const last=new Date(Date.parse(e.end_date!)-86400000);
    return `Весь день · ${format.format(new Date(e.start_date!))}${last.toISOString().slice(0,10)!==e.start_date ? ` — ${format.format(last)}` : ""}`;
  }
  const format=new Intl.DateTimeFormat("ru-RU",{timeZone:zone,day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"});
  return `${format.format(new Date(e.starts_at))} — ${format.format(new Date(e.ends_at))} · ${zone}`;
}
export const calendarStatus:Record<CalendarEvent["status"],string>={confirmed:"Подтверждено",tentative:"Предварительно",cancelled:"Отменено",removed:"Нет в текущей выборке"};
