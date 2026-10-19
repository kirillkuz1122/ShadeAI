import {useCallback,useEffect,useRef,useState} from "react";
import {api,ProtocolError} from "../api/client";
import {calendarStatus,calendarTime,knownCalendarPage} from "../api/calendar";
import {useResource} from "../hooks/useResource";
import {ErrorNotice,Freshness,Loading,Pager} from "./common";

export function Calendar({apiKey}:{apiKey:string}) {
  const [offset,setOffset]=useState(0),[inactive,setInactive]=useState(false),[busy,setBusy]=useState(false),[message,setMessage]=useState("");
  const alive=useRef(true),request=useRef<AbortController|null>(null);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;request.current?.abort();};},[]);
  const load=useCallback(async(signal:AbortSignal)=>{
    const data=await api.calendar({apiKey,signal},offset,inactive);
    if(!knownCalendarPage(data))throw new ProtocolError();
    return data;
  },[apiKey,offset,inactive]);
  const state=useResource(load,30000);
  async function sync(){
    if(busy)return;
    const controller=new AbortController();request.current?.abort();request.current=controller;setBusy(true);setMessage("");
    try{
      const result=await api.syncCalendar({apiKey,signal:controller.signal});
      if(alive.current && !controller.signal.aborted)setMessage(result.status==="ready"?"Календарь синхронизирован.":"Синхронизация не настроена.");
    }catch{
      if(alive.current && !controller.signal.aborted)setMessage("Синхронизация не подтверждена. Проверьте отметку актуальности кэша.");
    }finally{
      if(alive.current && !controller.signal.aborted){setBusy(false);state.refresh();}
    }
  }
  return <section className="panel" aria-labelledby="calendar-title">
    <header className="panel-heading"><div><p className="eyebrow">Локальное расписание</p><h2 id="calendar-title">События календаря</h2></div>
      <button disabled={busy || !state.data?.configured} onClick={()=>void sync()}>{busy?"Синхронизация…":"Синхронизировать"}</button>
    </header>
    <Freshness updatedAt={state.updatedAt} loading={state.loading} stale={!!state.error || !!state.data?.stale}/>
    {message && <p role="status" className="notice">{message}</p>}
    {!!state.error && <ErrorNotice error={state.error} retry={state.refresh}/>}
    <label className="help"><input type="checkbox" checked={inactive} onChange={e=>{setInactive(e.target.checked);setOffset(0);}}/> Показывать отменённые и исчезнувшие события</label>
    {state.loading && !state.data && <Loading/>}
    {state.data && <>
      {!state.data.configured ? <p className="empty">Локальный календарь ещё не подключён.</p> : <>
        {state.data.stale && <p className="notice">Кэш устарел или обновляется. События могут отличаться от календаря.</p>}
        <p className="help">Последняя синхронизация: {state.data.last_success ? new Intl.DateTimeFormat("ru-RU",{timeZone:state.data.timezone,dateStyle:"short",timeStyle:"short"}).format(new Date(state.data.last_success)) : "ещё не выполнялась"}. Часовой пояс: {state.data.timezone}. Календарь не управляет домом и пока не отправляет напоминания.</p>
        {state.data.events.length ? <ul className="record-list">{state.data.events.map(event=><li className="record-copy" key={event.id}>
          <strong>{event.summary || "Событие без названия"}</strong><p>{calendarTime(event,state.data!.timezone)}</p>
          {event.location && <p>{event.location}</p>}<small>{calendarStatus[event.status]}{event.busy?" · Время занято":""}</small>
        </li>)}</ul> : <p className="empty">В этом окне событий нет.</p>}
        <Pager offset={offset} total={state.data.total} loading={state.loading} onChange={setOffset} pageSize={50}/>
      </>}
    </>}
  </section>;
}
