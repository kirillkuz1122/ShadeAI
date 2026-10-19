async(page)=>{
  const errors=[],external=[],posts=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(!['127.0.0.1','localhost'].includes(new URL(r.url()).hostname))external.push(r.url());});
  const id='cal_'+'a'.repeat(32),generation='11111111-1111-1111-1111-111111111111',scope='b'.repeat(64);
  let approved=false,conflict=false,stale=false,acked=false,denied=false;
  const policy={version:1,enabled:true,allowed_targets:['switch.dnd'],max_duration_seconds:28800};
  await page.route('**/api/v1/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    if(path.endsWith('/health'))return route.fulfill({json:{status:'degraded',uptime:10,db_connected:true,db_size:'1MB',db_size_bytes:1024,ha_connected:false,ha_status:'not_configured',llm_status:'not_loaded',services:{calendar:'ready',meeting_mode:'ready'}}});
    if(denied)return route.fulfill({status:401,json:{detail:'private-raw-error'}});
    if(request.method()==='POST'){
      const body=request.postDataJSON();posts.push({path,body});
      if(path.endsWith('/ack')){acked=true;return route.fulfill({json:{status:'acknowledged'}});}
      if(body.decision==='approve'){
        if(body.policy_scope!==scope || body.event_revision!==1 || JSON.stringify(body.targets)!=='["switch.dnd"]')throw Error('unbound consent');
        if(conflict){stale=true;return route.fulfill({status:409,json:{detail:{code:'MEETING_CHANGED',text:'private-raw-error'}}});}
        approved=true;
      }else{approved=false;}
      return route.fulfill({json:{status:approved?'approved':'disabled'}});
    }
    if(path.endsWith('/calendar/meeting'))return route.fulfill({json:{status:'ready',policy,plans:[],leases:[{entity_id:'switch.dnd',generation,state:acked?'completed':'unknown',reason:'CORE_RESTARTED',members:[],event_id:1,updated_at:'2026-10-19T04:00:00Z'}],history:[]}});
    if(path.endsWith('/meeting'))return route.fulfill({json:{policy,event_id:id,event_revision:1,policy_scope:scope,eligible:!stale,stale,starts_at:'2026-10-19T04:00:00Z',ends_at:'2026-10-19T05:00:00Z',status:approved?'approved':'not_approved',targets:approved?['switch.dnd']:[],approval_valid:approved && !stale,started_targets:[]}});
    if(path.endsWith('/calendar/events'))return route.fulfill({json:{status:'ready',configured:true,stale:false,timezone:'Asia/Yekaterinburg',last_success:null,total:1,events:[{id,summary:'Синтетическая встреча 24',location:null,starts_at:'2026-10-19T04:00:00Z',ends_at:'2026-10-19T05:00:00Z',start_date:null,end_date:null,all_day:false,status:'confirmed',busy:true,revision:1,updated_at:'2026-10-19T04:00:00Z'}]}});
    return route.fulfill({json:{items:[],events:[],total:0}});
  });
  await page.addInitScript(()=>localStorage.setItem('shade_api_key','task24-synthetic-browser-key-00001'));
  await page.goto('http://127.0.0.1:5187');
  await page.getByRole('button',{name:'Календарь',exact:true}).click();
  await page.getByRole('button',{name:'Режим дома для встречи',exact:true}).click();
  const approve=page.getByRole('button',{name:'Подтверждаю выбранный режим',exact:true});
  await approve.waitFor();if(await approve.isEnabled())throw Error('no explicit target');
  if(posts.length)throw Error('GET sent commands');
  await page.getByRole('checkbox',{name:'switch.dnd',exact:true}).check();await approve.click();
  await page.getByText('Согласие сохранено · Условия действуют',{exact:true}).waitFor();
  conflict=true;await page.getByRole('checkbox',{name:'switch.dnd',exact:true}).check();await approve.click();
  await page.getByText('Условия изменились. Обновите и проверьте их заново.',{exact:true}).waitFor();
  await page.getByText('Кэш календаря устарел: новое включение недоступно.',{exact:true}).waitFor();
  if(posts.length!==2 || await approve.isEnabled())throw Error('conflict retried or approval enabled on stale');
  const disable=page.getByRole('button',{name:'Отключить для этой встречи',exact:true});
  if(!await disable.isEnabled())throw Error('stale blocked disabling');await disable.click();
  const ack=page.getByRole('button',{name:'Закрыть неопределённый результат',exact:true});
  if(await ack.isEnabled())throw Error('ack without physical checkbox');
  await page.getByRole('checkbox',{name:'Я проверил устройство и при необходимости восстановил его вручную'}).check();await ack.click();
  await page.getByText('Обработка завершена',{exact:true}).waitFor();
  const body=posts.at(-1).body;if(body.generation!==generation || body.checked!==true)throw Error('invalid ack');
  await page.setViewportSize({width:320,height:800});
  if(!await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))throw Error('mobile overflow');
  await page.screenshot({path:'output/playwright/task24-meeting-mobile.png'});
  denied=true;await page.evaluate(()=>window.dispatchEvent(new Event('online')));
  await page.getByText('Ключ не принят. Проверьте его в настройках подключения.').first().waitFor();
  const text=await page.locator('body').innerText();
  if(text.includes('Синтетическая встреча 24') || text.includes('private-raw-error') || text.includes('switch.dnd'))throw Error('auth leaked protected data');
  if(errors.length || external.length)throw Error(JSON.stringify({errors,external}));
  return {result:'PASS',checks:['explicit targets','scope pinned','409 not retried','stale disables approval, allows disable','unknown checked ack','320px','401 clears'],posts:posts.length,errors,external};
}
