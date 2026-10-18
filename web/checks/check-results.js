async (page) => {
  const failures = [], external = [];
  page.on('pageerror', e => failures.push(e.message));
  page.on('request', r => { if (!['127.0.0.1','localhost'].includes(new URL(r.url()).hostname)) external.push(r.url()); });
  const result = {
    processor:'llm',llm:true,schema_version:1,category:'reminder',priority:'default',intent:'reminder',
    entities:{subject:'Синтетическое дело только в карточке',location:'Зал 42',service:null},
    time:{source:'завтра в 07:00',timezone:'Asia/Yekaterinburg',at:'2026-10-19T02:00:00Z',date:null,resolution:'exact'},
    action_authorized:false,
  };
  let phase = 'pending', detailCalls=0;
  function notification() { return {
    id:1,app_name:'ru.ozon.app.android',title:'Тест результата Core',text:'Синтетическая запись',
    timestamp:'2026-10-18T10:00:00Z',created_at:'2026-10-18T10:00:01Z',priority:'default',event_id:'11111111-1111-4111-8111-111111111111',
    status: phase === 'pending' ? 'stored' : 'processed',processing_status:phase === 'pending' ? 'pending' : phase === 'failed' ? 'failed' : 'processed',
    category:phase === 'pending' ? null : 'reminder',processing_attempts:1,
    processing_error_code:phase === 'failed' ? 'LLM_BAD_RESPONSE' : null,
    processed_data:phase === 'pending' || phase === 'failed' ? null : phase === 'diagnostic' ? {processor:'diagnostic',llm:false} : {...result,schema_version:phase === 'future' ? 99 : 1},
  }; }
  await page.route('**/api/v1/**', async route => {
    const url=new URL(route.request().url());
    if (url.pathname.endsWith('/health')) return route.fulfill({json:{status:'ok',uptime:12,ha_connected:false,llm_status:'ready',db_size:'1 MB',db_connected:true,db_size_bytes:1024,ha_status:'not_configured',services:{}}});
    if (url.pathname.endsWith('/notifications/1')) {
      detailCalls++;
      if (phase === 'unauthorized') return route.fulfill({status:401,json:{detail:'private-auth-body'}});
      if (phase === 'gone') return route.fulfill({status:404,json:{detail:'private-body-never-show'}});
      return route.fulfill({json:notification()});
    }
    if (url.pathname.endsWith('/notifications')) return route.fulfill({json:{items:[notification()],total:1}});
    return route.fulfill({json:{events:[],total:0}});
  });
  await page.addInitScript(() => localStorage.setItem('shade_api_key','synthetic-browser-task19-key-only'));
  await page.reload();
  const open = () => page.getByRole('button',{name:'Открыть уведомление: Тест результата Core'}).click();
  const close = () => page.getByRole('button',{name:'Закрыть запись'}).click();
  await open();
  await page.getByText('Результат разбора ещё не получен.',{exact:true}).waitFor();
  phase='processed';
  await page.getByRole('heading',{name:'Локальный разбор'}).waitFor({timeout:10000});
  await page.getByText(result.entities.subject,{exact:true}).waitFor();
  if (!(await page.locator('dialog').innerText()).includes('07:00:00')) throw Error('wrong timezone');
  if (await page.locator('pre').count()) throw Error('raw JSON shown');
  await page.setViewportSize({width:320,height:800});
  if (!await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)) throw Error('320px overflow');
  await page.screenshot({path:'output/playwright/task19-result-mobile.png'});
  await close();
  if ((await page.locator('body').innerText()).includes(result.entities.subject)) throw Error('entity leaked outside details');
  phase='future'; await open();
  await page.getByText(/Формат результата не поддерживается/).waitFor(); await close();
  phase='diagnostic'; await open();
  await page.getByText(/Анализ текста и LLM не выполнялись/).waitFor(); await close();
  phase='failed'; await open();
  await page.getByText('Модель вернула неподтверждённые или неполные сведения',{exact:true}).waitFor(); await close();
  phase='processed'; await open();
  await page.getByText(result.entities.subject,{exact:true}).waitFor();
  phase='gone';
  await page.getByText('Запись уже удалена или срок её хранения истёк.',{exact:true}).waitFor({timeout:10000});
  if ((await page.locator('body').innerText()).includes(result.entities.subject)) throw Error('404 kept private fields');
  if ((await page.locator('body').innerText()).includes('private-body-never-show')) throw Error('raw API error leaked');
  await close();
  phase='processed'; await open();
  await page.getByText(result.entities.subject,{exact:true}).waitFor();
  phase='unauthorized';
  await page.getByText('Ключ не принят. Проверьте его в настройках подключения.',{exact:true}).waitFor({timeout:10000});
  if ((await page.locator('body').innerText()).includes(result.entities.subject)) throw Error('401 kept private fields');
  await close();
  if (failures.length || external.length) throw Error(JSON.stringify({failures,external}));
  return {result:'PASS', detailCalls, checks:['pending→processed poll','typed result','timezone','320px','details-only entities','unknown schema','diagnostic','failed','404 clears fields','401 clears fields'], failures,external};
}
