import {useCallback,useEffect,useRef,useState} from 'react';
import {api,ApiError,ProtocolError} from '../api/client';
import {knownMeetingPage,knownMeetingView,meetingState,meetingReason} from '../api/meeting';
import type {MeetingView} from '../api/meeting';
import type {CalendarEvent} from '../api/calendar';
import {useResource} from '../hooks/useResource';
import {ErrorNotice,Freshness} from './common';

function useMutation(){
  const [busy,setBusy]=useState(false),[message,setMessage]=useState('');
  const pending=useRef<AbortController|null>(null);
  useEffect(()=>()=>pending.current?.abort(),[]);
  async function run(action:(signal:AbortSignal)=>Promise<unknown>,done:()=>void){
    if(pending.current)return;
    const controller=new AbortController();pending.current=controller;setBusy(true);setMessage('');
    try{
      await action(controller.signal);
      if(!controller.signal.aborted)setMessage('Решение сохранено. Состояние устройства проверяйте в журнале.');
    }catch(error){
      if(!controller.signal.aborted)setMessage(error instanceof ApiError && error.status===409?'Условия изменились. Обновите и проверьте их заново.':'Результат запроса не подтверждён. Обновите состояние; автоматического повтора нет.');
    }finally{
      if(!controller.signal.aborted){pending.current=null;setBusy(false);done();}
    }
  }
  return {busy,message,run};
}
export function MeetingControl({apiKey,event,stale}:{apiKey:string;event:CalendarEvent;stale:boolean}){
  const [open,setOpen]=useState(false);
  return <div><button onClick={()=>setOpen(v=>!v)} aria-expanded={open}>{open?'Скрыть режим встречи':'Режим дома для встречи'}</button>
    {open && <MeetingDecision key={`${event.id}:${event.revision}:${apiKey}`} apiKey={apiKey} event={event} stale={stale}/>}</div>;
}
function MeetingDecision({apiKey,event,stale}:{apiKey:string;event:CalendarEvent;stale:boolean}){
  const load=useCallback(async(signal:AbortSignal)=>{
    const data=await api.meeting({apiKey,signal},event.id);
    if(!knownMeetingView(data) || data.event_id!==event.id)throw new ProtocolError();
    return data;
  },[apiKey,event.id]);
  const state=useResource(load,10000),mutation=useMutation();
  return <div className="notice meeting-panel">
    <Freshness updatedAt={state.updatedAt} loading={state.loading} stale={!!state.error || stale || !!state.data?.stale}/>
    {!!state.error && <ErrorNotice error={state.error} retry={state.refresh}/>}
    {state.data && <MeetingForm key={`${state.data.policy_scope}:${state.data.status}:${state.data.started_targets.join(",")}`} data={{...state.data,stale:state.data.stale || stale}}
      blocked={!!state.error || state.loading || state.data.event_revision!==event.revision || mutation.busy}
      decide={(decision,targets)=>void mutation.run(signal=>api.decideMeeting({apiKey,signal},event.id,decision==='approve'?
        {decision,event_revision:state.data!.event_revision,policy_scope:state.data!.policy_scope,targets}:
        {decision,event_revision:state.data!.event_revision}),state.refresh)}/>}
    {mutation.message && <p role="status">{mutation.message}</p>}
  </div>;
}
function MeetingForm({data,blocked,decide}:{data:MeetingView;blocked:boolean;decide:(d:'approve'|'disable',targets:string[])=>void}){
  const [selected,setSelected]=useState<string[]>([]);
  const available=data.policy.allowed_targets.filter(t=>!data.started_targets.includes(t));
  return <>
    <p>{meetingState[data.status]}{data.approval_valid?' · Условия действуют':''}</p>
    <p>На время встречи включить выбранный переключатель «Не беспокоить» (до 8 часов). Выключить после последней пересекающейся встречи только если включение принадлежит Shade и ручное изменение не обнаружено. Уже включённое устройство не выключаем.</p>
    {!data.policy.enabled && <p>Режим встреч выключен в настройках Core.</p>}
    {data.stale && <p>Кэш календаря устарел: новое включение недоступно.</p>}
    {data.targets.length>0 && <p>Сохранённый выбор: {data.targets.join(', ')}</p>}
    {data.started_targets.length>0 && <p>Уже запускались: {data.started_targets.join(', ')}. Повторное подтверждение этой версии события не запускает их заново.</p>}
    <fieldset disabled={blocked || !data.policy.enabled || !data.eligible || data.stale}>
      <legend>Разрешённые устройства</legend>
      {available.map(target=><label className="help" key={target}><input type="checkbox" checked={selected.includes(target)} onChange={e=>setSelected(v=>e.target.checked?[...v,target]:v.filter(t=>t!==target))}/> {target}</label>)}
      <button disabled={!selected.length} onClick={()=>decide('approve',selected)}>Подтверждаю выбранный режим</button>
    </fieldset>
    <button disabled={blocked} onClick={()=>decide('disable',[])}>Отключить для этой встречи</button>
  </>;
}
export function MeetingJournal({apiKey}:{apiKey:string}){
  const load=useCallback(async(signal:AbortSignal)=>{
    const page=await api.meetingState({apiKey,signal});if(!knownMeetingPage(page))throw new ProtocolError();return page;
  },[apiKey]);
  const state=useResource(load,10000),mutation=useMutation();
  return <section className="notice meeting-panel" aria-label="Журнал режима встреч"><h3>Режим дома: состояние устройств</h3>
    <p>Команды по календарю выполняет Core. Напоминания на телефоне включаются отдельно в Android.</p>
    <Freshness updatedAt={state.updatedAt} loading={state.loading} stale={!!state.error}/>
    {!!state.error && <ErrorNotice error={state.error} retry={state.refresh}/>}
    {mutation.message && <p role="status">{mutation.message}</p>}
    {state.data && <>
      {!state.data.policy.enabled && <p>Режим встреч выключен в Core.</p>}
      {!state.data.leases.length && <p>Устройств в режиме встречи пока нет.</p>}
      <ul className="record-list">{state.data.leases.map(lease=><li key={`${lease.entity_id}:${lease.generation}`}><strong>{lease.entity_id}</strong>
        <p>{meetingState[lease.state]}</p>{lease.reason && meetingReason[lease.reason] && <p>{meetingReason[lease.reason]}</p>}
        <p>Участвующих встреч: {lease.members.length}</p>
        {lease.state==='unknown' && <MeetingAck key={`${lease.generation}:${lease.updated_at}`} disabled={mutation.busy || !!state.error || state.loading}
          confirm={()=>void mutation.run(signal=>api.acknowledgeMeeting({apiKey,signal},lease.entity_id,lease.generation),state.refresh)}/>}
      </li>)}</ul>
      <h4>Последние изменения</h4>
      <ul>{state.data.history.map(log=><li key={log.id}>{log.entity_id} · {meetingState[log.state]}{log.reason && meetingReason[log.reason]?` · ${meetingReason[log.reason]}`:''}</li>)}</ul>
    </>}
  </section>;
}
function MeetingAck({disabled,confirm}:{disabled:boolean;confirm:()=>void}){
  const [checked,setChecked]=useState(false);
  return <div><label><input type="checkbox" disabled={disabled} checked={checked} onChange={e=>setChecked(e.target.checked)}/> Я проверил устройство и при необходимости восстановил его вручную</label>
    <button disabled={disabled || !checked} onClick={confirm}>Закрыть неопределённый результат</button><p>Подтверждение очищает блокировку; команд устройству не отправляет.</p></div>;
}
