async (page) => {
  const errors=[],external=[],syncCalls=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(!['127.0.0.1','localhost'].includes(new URL(r.url()).hostname))external.push(r.url());});
  let denied=false,stale=false,renamed=false;
  const rows=Array.from({length:51},(_,i)=>({id:'cal_'+i.toString(16).padStart(32,'0'),summary:i===0?'Синтетическая встреча':i===1?'Событие на весь день':`Событие ${i+1}`,location:i===0?'Комната 1':null,
    starts_at:'2026-10-19T05:00:00Z',ends_at:'2026-10-19T06:00:00Z',start_date:i===1?'2026-10-19':null,end_date:i===1?'2026-10-20':null,all_day:i===1,status:'confirmed',busy:true,revision:1,updated_at:'2026-10-19T03:00:00Z'}));
  const cancelled={...rows[0],id:'cal_'+'f'.repeat(32),summary:'Отменённая встреча',status:'cancelled',busy:false};
  await page.route('**/api/v1/**',async route=>{
    const request=route.request(),url=new URL(request.url()),path=url.pathname;
    if(path.endsWith('/health'))return route.fulfill({json:{status:'degraded',uptime:10,db_connected:true,db_size:'1MB',db_size_bytes:1024,ha_connected:false,ha_status:'not_configured',llm_status:'not_loaded',services:{analytics:'disabled',calendar:'ready'}}});
    if(denied)return route.fulfill({status:401,json:{detail:'private-error-body'}});
    if(path.endsWith('/calendar/sync')){
      syncCalls.push(request.method);if(syncCalls.length===1){renamed=true;return route.fulfill({json:{status:'ready'}});}
      stale=true;return route.fulfill({status:503,json:{detail:{code:'CALENDAR_UNAVAILABLE',text:'private-server-error'}}});
    }
    if(path.endsWith('/calendar/events')){
      const offset=Number(url.searchParams.get('offset')??0),inactive=url.searchParams.get('include_inactive')==='true';
      const current=rows.map((row,i)=>i===0 && renamed?{...row,summary:'Встреча после изменения',revision:2}:row);
      if(inactive)current.push(cancelled);
      return route.fulfill({json:{status:stale?'CALENDAR_UNAVAILABLE':'ready',configured:true,stale,timezone:'Asia/Yekaterinburg',last_success:'2026-10-19T03:00:00Z',window_start:'2026-10-12T00:00:00Z',window_end:'2026-12-18T00:00:00Z',error_code:stale?'CALENDAR_UNAVAILABLE':null,total:current.length,events:current.slice(offset,offset+50)}});
    }
    return route.fulfill({json:{notifications:[],items:[],events:[],total:0}});
  });
  await page.addInitScript(()=>localStorage.setItem('shade_api_key','task23-synthetic-browser-key-00001'));
  await page.goto('http://127.0.0.1:5187');
  await page.getByRole('button',{name:'Календарь',exact:true}).click();
  await page.getByRole('heading',{name:'События календаря',exact:true}).waitFor();
  await page.getByText('Синтетическая встреча',{exact:true}).waitFor();
  await page.getByText(/19 окт.*, 10:00/).first().waitFor();
  await page.getByText(/Весь день · 19 октября 2026/).waitFor();
  await page.getByText('1–50 из 51',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Далее',exact:true}).click();
  await page.getByText('51–51 из 51',{exact:true}).waitFor();
  if(await page.getByText('Синтетическая встреча',{exact:true}).count())throw Error('old page survived');
  await page.getByRole('button',{name:'Назад',exact:true}).click();
  await page.getByRole('button',{name:'Синхронизировать',exact:true}).click();
  await page.getByText('Встреча после изменения',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Синхронизировать',exact:true}).click();
  await page.getByText('Кэш устарел или обновляется. События могут отличаться от календаря.',{exact:true}).waitFor();
  if(syncCalls.length!==2)throw Error('sync blindly retried');
  await page.getByRole('checkbox',{name:'Показывать отменённые и исчезнувшие события'}).check();
  await page.getByRole('button',{name:'Далее',exact:true}).click();
  await page.getByText('Отменённая встреча',{exact:true}).waitFor();
  await page.getByText('Отменено',{exact:true}).waitFor();
  await page.setViewportSize({width:320,height:800});
  await page.getByRole('heading',{name:'События календаря',exact:true}).scrollIntoViewIfNeeded();
  if(!await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))throw Error('mobile overflow');
  await page.screenshot({path:'output/playwright/task23-calendar-mobile.png'});
  denied=true;
  await page.getByRole('checkbox',{name:'Показывать отменённые и исчезнувшие события'}).uncheck();
  await page.getByText('Ключ не принят. Проверьте его в настройках подключения.',{exact:true}).waitFor();
  const body=await page.locator('body').innerText();
  if(body.includes('Отменённая встреча') || body.includes('Встреча после изменения') || body.includes('private-'))throw Error('401 leaked prior data/raw error');
  if(errors.length || external.length)throw Error(JSON.stringify({errors,external}));
  return {result:'PASS',checks:['Core timezone','all-day no shift','50-row pagination clears old page','updated event','stale cache','sync not retried','cancelled filter','401 clears','320px'],errors,external};
}
