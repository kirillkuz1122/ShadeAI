import {useCallback, useEffect, useRef, useState} from "react";
import {api, ApiError, ProtocolError} from "../api/client";
import {allowedLight, decisionLabels, knownRule, knownAutomationPage, knownHintPage, ruleLabels, type AutomationRule} from "../api/automation";
import {useResource} from "../hooks/useResource";
import {ErrorNotice, Freshness, Loading, Pager, time} from "./common";
import {NotificationDetail} from "./Notifications";

function mutationError(error: unknown) {
  const detail = error instanceof ApiError ? error.detail : null;
  const code = detail && typeof detail === "object" && "code" in detail ? detail.code : null;
  if (code === "AUTOMATION_CHANGED" || code === "AUTOMATION_SOURCE_STALE")
    return "Условия изменились или устарели. Обновите предложения и проверьте их заново.";
  if (code === "AUTOMATION_TARGET_NOT_ALLOWED") return "Эта цель больше не разрешена в настройках Core.";
  if (error instanceof ApiError && error.status === 401) return "Ключ не принят. Проверьте подключение.";
  return "Решение не подтверждено сервером. Обновите список перед повтором.";
}
function RuleHistory({id, apiKey}: {id:string; apiKey:string}) {
  const load = useCallback((signal:AbortSignal) => api.automation({apiKey,signal},id),[apiKey,id]);
  const state = useResource(load,0);
  return <div aria-label="История решений">
    {state.loading && <Loading label="Загрузка истории…"/>}
    {!!state.error && <ErrorNotice error={state.error} retry={state.refresh}/>}
    {state.data && <ul>{state.data.history.map(item => <li key={item.id}>
      {Object.hasOwn(decisionLabels,item.decision) ? decisionLabels[item.decision] : "Служебное изменение"}
      {" · "}{time(item.created_at)}
    </li>)}</ul>}
  </div>;
}
function RuleCard({row, targets, busy, decide, apiKey}: {row:AutomationRule; targets:string[]; busy:boolean;
  decide:(row:AutomationRule, decision:"accept"|"reject"|"disable",target?:string)=>void; apiKey:string}) {
  const [target,setTarget] = useState("");
  const [history,setHistory] = useState(false);
  const verb = row.trigger.kind === "arrival_home" ? "Включать" : "Выключать";
  const validTarget = targets.includes(target) && allowedLight(target);
  return <article className="rule-card" aria-label={row.name}>
    <p className="eyebrow">{ruleLabels[row.status]}</p><h3>{row.name}</h3>
    <p>Окно {row.trigger.window_start}–{row.trigger.window_end}{row.trigger.wraps_midnight ? " · через полночь" : ""} · {row.trigger.timezone}</p>
    <p>Совпало {row.evidence.support_days} из {row.evidence.eligible_days} дней.
      {" "}Регулярность {Math.round(row.confidence*100)}% — оценка алгоритма, не вероятность.</p>
    {!row.source_current && <p className="notice">Профиль изменился или устарел. Перед новым решением обновите предложения.</p>}
    {row.action && <p>{verb}: <strong>{row.action.entity_id}</strong></p>}
    {row.executor_status === "not_implemented" && <p className="help">Исполнитель ещё не подключён. Сейчас команды устройствам не отправляются.</p>}
    {row.status !== "accepted" && <form onSubmit={event => {event.preventDefault(); if(validTarget) decide(row,"accept",target);}}>
      <label>Светильник для сценария
        <select value={validTarget ? target : ""} onChange={e=>setTarget(e.target.value)} disabled={busy || !row.source_current}>
          <option value="">Выберите разрешённое устройство</option>
          {targets.map(item=><option key={item} value={item}>{item}</option>)}
        </select>
      </label>
      {!targets.length && <p className="help">Разрешённые светильники пока не заданы в настройках Core.</p>}
      <div className="rule-actions">
        <button className="primary" disabled={busy || !row.source_current || !validTarget} type="submit">
          {validTarget ? `Разрешить: ${verb.toLowerCase()} ${target}` : "Разрешить сценарий"}
        </button>
        {row.status !== "rejected" && <button type="button" disabled={busy} onClick={()=>decide(row,"reject")}>Отклонить</button>}
      </div>
    </form>}
    {row.status === "accepted" && <button disabled={busy} onClick={()=>decide(row,"disable")}>Выключить сценарий</button>}
    <button className="text-button" aria-expanded={history} onClick={()=>setHistory(v=>!v)}>{history ? "Скрыть историю" : "История решений"}</button>
    {history && <RuleHistory id={row.id} apiKey={apiKey}/>}
  </article>;
}
function Hints({apiKey}: {apiKey:string}) {
  const [after,setAfter] = useState(0);
  const [selected,setSelected] = useState<{feed:string|null;id:number}|null>(null);
  const feed = useRef<string|null>(null);
  const load = useCallback(async(signal:AbortSignal) => {
    const data=await api.hints({apiKey,signal},after);
    if(!knownHintPage(data)) throw new ProtocolError();
    return data;
  },[apiKey,after]);
  const state = useResource(load);
  useEffect(()=>{
    if (state.data && ((feed.current && feed.current !== state.data.feed_id) || state.data.latest_id < after)) {setAfter(0);setSelected(null);}
    if (state.data) feed.current = state.data.feed_id;
  },[state.data,after]);
  return <section className="hint-panel" aria-labelledby="hints-title">
    <h3 id="hints-title">Локальные подсказки</h3>
    {!!state.error && <ErrorNotice error={state.error} retry={state.refresh}/>}
    {state.data && (state.data.hints.length ? <ul>{state.data.hints.map(hint=><li key={hint.id}>
      <p>{hint.kind === "arrival_delivery" ? "Вы дома. В Core есть событие доставки." : "Подсказка нового типа. Обновите клиент."}</p>
      <small>{time(hint.created_at)}</small>{" "}
      {Number.isSafeInteger(hint.notification_id) && hint.notification_id > 0 && <button className="text-button"
        onClick={()=>setSelected({feed:state.data!.feed_id,id:hint.notification_id})}>Открыть контекст Core</button>}
    </li>)}</ul> : <p className="help">Новых подсказок пока нет.</p>)}
    {state.data && state.data.next_id < state.data.latest_id && <button onClick={()=>setAfter(state.data!.next_id)}>Следующие подсказки</button>}
    {selected && selected.feed === state.data?.feed_id && <NotificationDetail id={selected.id} apiKey={apiKey} close={()=>setSelected(null)}/>}
  </section>;
}
export function Automations({apiKey}: {apiKey:string}) {
  const [offset,setOffset] = useState(0);
  const [busy,setBusy] = useState(false);
  const [message,setMessage] = useState("");
  const controller = useRef<AbortController|null>(null), alive = useRef(true);
  const load = useCallback(async(signal:AbortSignal) => {
    const data=await api.automations({apiKey,signal},offset);
    if(!knownAutomationPage(data)) throw new ProtocolError();
    return data;
  },[apiKey,offset]);
  const state = useResource(load);
  useEffect(()=>{alive.current=true; return()=>{alive.current=false;controller.current?.abort();};},[]);
  async function mutate(work:(signal:AbortSignal)=>Promise<unknown>, success:string) {
    if(busy) return;
    const current = new AbortController();controller.current=current;setBusy(true);setMessage("");
    try {await work(current.signal);if(alive.current){setMessage(success);state.refresh();}}
    catch(error){if(alive.current){setMessage(mutationError(error));state.refresh();}}
    finally{if(alive.current){setBusy(false);controller.current=null;}}
  }
  function decide(row:AutomationRule, decision:"accept"|"reject"|"disable", target?:string) {
    void mutate(signal=>api.decideAutomation({apiKey,signal},row.id,{decision,version:row.version,...(target ? {target_entity:target} : {})}),
      decision === "accept" ? "Выбранный сценарий подтверждён." : decision === "reject" ? "Предложение отклонено." : "Сценарий выключен.");
  }
  return <section className="panel" aria-labelledby="automations-title">
    <header className="panel-heading"><div><p className="eyebrow">Под контролем пользователя</p><h2 id="automations-title">Предложения сценариев</h2></div>
      <button disabled={busy || state.loading} onClick={()=>void mutate(signal=>api.refreshAutomations({apiKey,signal}),"Предложения обновлены.")}>Обновить предложения</button>
    </header>
    <Freshness updatedAt={state.updatedAt} loading={state.loading} stale={!!state.error}/>
    {message && <p role="status" className="notice">{message}</p>}
    {!!state.error && <ErrorNotice error={state.error} retry={state.refresh}/>}
    {state.loading && !state.data && <Loading/>}
    {state.data && <>
      {!state.data.automations.length && <p className="empty">Предложений пока нет. Нужен подтверждённый профиль присутствия с достаточной историей.</p>}
      {state.data.automations.map((row,index)=>knownRule(row) ? <RuleCard key={`${row.id}:${row.version}`} row={row} apiKey={apiKey}
        targets={state.data!.allowed_targets.filter(allowedLight)} busy={busy} decide={decide}/> : <p key={`unsupported-${index}`} className="notice">Формат предложения не поддерживается. Обновите клиент.</p>)}
      <Pager offset={offset} total={state.data.total} loading={state.loading || busy} onChange={setOffset}/>
    </>}
    <Hints apiKey={apiKey}/>
  </section>;
}
