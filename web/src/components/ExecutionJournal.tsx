import {useCallback, useEffect, useRef, useState} from "react";
import {api, ApiError, ProtocolError} from "../api/client";
import {knownRunPage, runReasons, runStates, type AutomationRun} from "../api/automation";
import {useResource} from "../hooks/useResource";
import {ErrorNotice, Loading, time} from "./common";

export function ExecutionJournal({apiKey}:{apiKey:string}) {
  const [message,setMessage]=useState(""), [busy,setBusy]=useState<number|null>(null);
  const [blocked,setBlocked]=useState(false);
  const alive=useRef(true), request=useRef<AbortController|null>(null);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;request.current?.abort();};},[]);
  const load=useCallback(async(signal:AbortSignal)=>{
    const page=await api.automationRuns({apiKey,signal});
    if(!knownRunPage(page))throw new ProtocolError();
    return page;
  },[apiKey]);
  const state=useResource(load,2000);
  async function cancel(row:AutomationRun) {
    if(busy!==null || !row.cancellable)return;
    request.current?.abort();const controller=new AbortController();request.current=controller;
    setBusy(row.id);setMessage("");
    try {
      const result=await api.cancelAutomationRun({apiKey,signal:controller.signal},row.id);
      if(result.status!=="cancelled")throw new ProtocolError();
      if(alive.current && !controller.signal.aborted)setMessage("Ожидающее действие отменено.");
    } catch(error) {
      if(alive.current && !controller.signal.aborted){
        if(error instanceof ApiError && error.status===401)setBlocked(true);
        setMessage(error instanceof ApiError && error.status===409 ? "Отправка уже началась или действие завершено. Отмена не выполнена." : "Отмена не подтверждена. Проверьте журнал и подключение.");
      }
    } finally {
      if(alive.current && !controller.signal.aborted){setBusy(null);state.refresh();}
    }
  }
  return <section className="subpanel" aria-labelledby="execution-title">
    <header className="panel-heading"><div><p className="eyebrow">Последние 20 действий</p><h3 id="execution-title">Исполнение сценариев</h3></div>
      <button onClick={()=>{setBlocked(false);state.refresh();}} disabled={busy!==null}>Обновить журнал</button>
    </header>
    <p className="help">Отменить можно до начала отправки. Принятие команды HA не подтверждает физическое состояние света. Неизвестный результат автоматически не повторяется.</p>
    {message && <p role="status" className="notice">{message}</p>}
    {!!state.error && <ErrorNotice error={state.error} retry={state.refresh}/>}
    {state.loading && !state.data && <Loading/>}
    {!blocked && state.data && (state.data.runs.length ? <ul className="record-list">{state.data.runs.map(row=><li key={row.id} className="record-copy">
      <strong>{runStates[row.state]}</strong><p>{row.target_entity} · {row.service==="turn_on"?"Включить":"Выключить"}</p>
      <p>{runReasons[row.reason] ?? "Служебное состояние. Проверьте подробности в Core."}</p>
      <small>{time(row.created_at)}{row.cancellable && ` · Отправка не раньше ${time(row.due_at)}`}</small>
      {row.cancellable && <button disabled={busy!==null} onClick={()=>void cancel(row)}>Отменить действие</button>}
    </li>)}</ul> : <p className="help">Действий пока нет. Исполнение по умолчанию выключено.</p>)}
  </section>;
}
