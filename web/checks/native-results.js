async (page) => {
  const base = 'http://127.0.0.1:8003';
  const endpoint = `${base}/api/v1/notifications`;
  const key = 'task19-native-only-synthetic-key-01';
  const errors = [], external = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    if (new URL(route.request().url()).origin === base) return route.continue();
    external.push(new URL(route.request().url()).origin);
    return route.abort();
  });
  const response = await page.request.get(endpoint, {headers:{Authorization:`Bearer ${key}`}});
  if (!response.ok()) throw Error('Стенд Core недоступен');
  const {items} = await response.json();
  if (![2,3].includes(items.length) || !items.every(row => ['Синтетическая доставка order','Синтетическая доставка big','Курьер в пути'].includes(row.title))) {
    throw Error('Нужна только тестовая SQLite TASK-19');
  }
  await page.addInitScript(value => localStorage.setItem('shade_api_key', value), key);
  await page.goto(base);
  let nativeCount = 0;
  for (const row of items) {
    const detail = page.waitForResponse(response => response.url() === `${endpoint}/${row.id}` && response.ok());
    await page.getByRole('button',{name:`Открыть уведомление: ${row.title}`,exact:true}).click();
    const actual = await (await detail).json();
    if (actual.event_id !== row.event_id || actual.processing_status !== row.processing_status) {
      throw Error('Карточка прочитала другую запись');
    }
    if (row.processing_status === 'processed') {
      if (actual.processed_data?.llm !== true || actual.processed_data.action_authorized !== false) {
        throw Error('Некорректный native результат');
      }
      await page.getByRole('heading',{name:'Локальный разбор',exact:true}).waitFor();
      const rendered = await page.locator('dialog').innerText();
      if (!rendered.includes(actual.processed_data.time.timezone)) throw Error('Нет пояса разбора');
      nativeCount++;
    } else {
      if (row.processing_status !== 'failed') throw Error('Разбор записи не завершён');
      await page.getByText('Модель вернула неподтверждённые или неполные сведения',{exact:true}).waitFor();
    }
    await page.getByRole('button',{name:'Закрыть запись',exact:true}).click();
  }
  if (errors.length || external.length) throw Error(JSON.stringify({nativeCount,errors,external}));
  return {result:'PASS', nativeCount, rows:items.map(({id,event_id,processing_status})=>({id,event_id,processing_status})), errors:[], externalRequests:0};
}
