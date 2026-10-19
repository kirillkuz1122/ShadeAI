async (page) => {
  const errors=[], external=[], decisions=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(!['127.0.0.1','localhost'].includes(new URL(r.url()).hostname))external.push(r.url());});
  let row={id:'aut_'+'a'.repeat(32),source_habit_id:'hbt_'+'b'.repeat(32),name:'Контрольный сценарий прихода',status:'pending',version:1,
    trigger:{type:'presence_transition',entity_id:'binary_sensor.test',kind:'arrival_home',from_state:'off',to_state:'on',day_group:'weekdays',timezone:'Asia/Yekaterinburg',window_start:'17:15',window_end:'18:45',wraps_midnight:false},
    action:null,evidence:{support_days:12,eligible_days:15,dispersion_minutes:5},confidence:0.8,source_current:true,approval_valid:false,enabled:false,executable:false,executor_status:'not_implemented',created_at:'2026-10-19T00:00:00Z',updated_at:'2026-10-19T00:00:00Z'};
  const feed='11111111-1111-4111-8111-111111111111', target='light.synthetic_entry';
  const history=[{id:1,decision:'suggested',version:1,target_entity:null,created_at:row.created_at}];
  let conflict=false,denied=false;

  await page.route('**/api/v1/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    if(path.endsWith('/health'))return route.fulfill({json:{status:'degraded',uptime:10,db_connected:true,db_size:'1MB',db_size_bytes:1024,ha_connected:false,ha_status:'not_configured',llm_status:'not_loaded',services:{analytics:'ready',suggestions:'ready'}}});
    if(denied)return route.fulfill({status:401,json:{detail:'private-error-body'}});
    if(path.endsWith('/automations/refresh'))return route.fulfill({json:{status:'ready'}});
    if(path.endsWith('/decision')){
      const body=request.postDataJSON();decisions.push(body);
      if(conflict){conflict=false;return route.fulfill({status:409,json:{detail:{code:'AUTOMATION_CHANGED'}}});}
      if(body.version!==row.version)throw Error('wrong version');
      if(body.decision==='accept' && body.target_entity!==target)throw Error('target not explicitly selected');
      if('params' in body || 'action' in body)throw Error('unexpected arbitrary action');
      row={...row,version:row.version+1,status:body.decision==='accept'?'accepted':body.decision==='reject'?'rejected':'disabled',
        enabled:body.decision==='accept',approval_valid:body.decision==='accept',
        action:body.decision==='accept'?{entity_id:target,service:'turn_on',params:{}}:row.action};
      history.unshift({id:history.length+1,decision:body.decision,version:row.version,target_entity:row.action?.entity_id??null,created_at:row.updated_at});
      return route.fulfill({json:row});
    }
    if(path.endsWith('/automations/runs'))return route.fulfill({json:{status:'disabled',runs:[]}});
    if(path.endsWith('/automations'))return route.fulfill({json:{automations:[row],total:1,allowed_targets:[target],status:'ready',executor_status:'not_implemented'}});
    if(path.endsWith('/'+row.id))return route.fulfill({json:{...row,history}});
    if(path.endsWith('/hints'))return route.fulfill({json:{feed_id:feed,latest_id:1,next_id:1,hints:[{id:1,kind:'arrival_delivery',notification_id:1,created_at:row.created_at}]}});
    if(path.endsWith('/notifications/1'))return route.fulfill({json:{id:1,app_name:'ru.ozon.app.android',title:'Синтетический контекст',text:'private-synthetic-context-only-in-detail',timestamp:row.created_at,created_at:row.created_at,priority:'default',category:'delivery',event_id:null,status:'stored',processing_status:'pending',processing_attempts:0,processed_data:null}});
    return route.fulfill({json:{items:[],total:0,events:[]}});
  });
  await page.addInitScript(()=>localStorage.setItem('shade_api_key','task21-synthetic-browser-key-00000'));
  await page.goto('http://127.0.0.1:5187');
  await page.getByRole('button',{name:/Сценарии и подсказки/}).click();
  await page.getByRole('heading',{name:'Предложения сценариев'}).waitFor();
  await page.getByRole('heading',{name:row.name}).waitFor();
  if(!await page.getByRole('button',{name:'Разрешить сценарий',exact:true}).isDisabled())throw Error('implicit target approval');
  await page.getByText('Вы дома. В Core есть событие доставки.',{exact:true}).waitFor();
  if((await page.locator('body').innerText()).includes('private-synthetic-context'))throw Error('hint leaked private input');
  await page.getByRole('button',{name:'Открыть контекст Core'}).click();
  await page.getByText('private-synthetic-context-only-in-detail',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Закрыть запись'}).click();
  await page.getByRole('combobox').selectOption(target);
  await page.getByRole('button',{name:`Разрешить: включать ${target}`,exact:true}).click();
  await page.getByRole('button',{name:'Выключить сценарий',exact:true}).waitFor();
  if(decisions.length!==1 || decisions[0].target_entity!==target)throw Error('accept not explicit');
  await page.getByText('Исполнитель ещё не подключён. Сейчас команды устройствам не отправляются.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Выключить сценарий',exact:true}).click();
  await page.getByRole('button',{name:'Разрешить сценарий',exact:true}).waitFor();
  if(!await page.getByRole('button',{name:'Разрешить сценарий',exact:true}).isDisabled())throw Error('target silently retained');
  await page.setViewportSize({width:320,height:800});
  await page.getByRole('heading',{name:'Предложения сценариев'}).scrollIntoViewIfNeeded();
  if(!await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))throw Error('mobile overflow');
  await page.screenshot({path:'output/playwright/task21-suggestions-mobile.png'});
  await page.getByRole('button',{name:'Отклонить',exact:true}).click();
  await page.getByText('Отклонено',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Обновить предложения',exact:true}).click();
  await page.getByText('Предложения обновлены.',{exact:true}).waitFor();
  await page.getByText('Отклонено',{exact:true}).waitFor();
  await page.getByRole('button',{name:'История решений',exact:true}).click();
  await page.getByText(/Отклонено пользователем/).waitFor();
  await page.getByRole('button',{name:'Скрыть историю',exact:true}).click();
  conflict=true;
  await page.getByRole('combobox').selectOption(target);
  const before=decisions.length;
  await page.getByRole('button',{name:`Разрешить: включать ${target}`,exact:true}).click();
  await page.getByText(/Условия изменились или устарели/).waitFor();
  if(decisions.length!==before+1)throw Error('blind mutation retry');
  row={...row,trigger:{...row.trigger,type:'private-future-type'}};
  await page.getByRole('button',{name:'Обновить предложения',exact:true}).click();
  await page.getByText('Формат предложения не поддерживается. Обновите клиент.',{exact:true}).waitFor();
  if(await page.getByRole('combobox').count())throw Error('unknown rule can be approved');
  denied=true;
  await page.getByRole('button',{name:'Обновить предложения',exact:true}).click();
  await page.getByText('Ключ не принят. Проверьте его в настройках подключения.',{exact:true}).first().waitFor();
  const body=await page.locator('body').innerText();
  if(body.includes(row.name) || body.includes('private-error-body') || body.includes('private-future-type'))throw Error('401/unknown leaked old fields');
  if(errors.length || external.length)throw Error(JSON.stringify({errors,external}));
  return {result:'PASS',decisions:decisions.length,checks:['explicit target','accept/disable/reject/history','409 no blind retry','hint private context only in detail','unknown rule blocked','401 clears data','320px'],errors,external};
}
