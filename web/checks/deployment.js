async (page) => {
  const origin = new URL(page.url()).origin;
  const errors = [];
  const external = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (new URL(request.url()).origin !== origin) external.push(request.url());
  });
  await page.addInitScript(() => {
    window.__shadeCspViolations = [];
    document.addEventListener('securitypolicyviolation', e => window.__shadeCspViolations.push(e.violatedDirective));
  });
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.getByText('Подключите свою историю', { exact: true }).waitFor();
  await page.getByLabel('API-ключ Shade').fill('task08-synthetic-local-owner-key-00001');
  await page.getByRole('button', { name: 'Сохранить ключ' }).click();
  await page.getByText('Стенд TASK-08', { exact: true }).waitFor();
  await page.locator('.notification-row').first().click();
  await page.getByRole('dialog').waitFor();
  await page.getByText('Синтетическая посылка для проверки развёртывания', { exact: true }).waitFor();
  await page.keyboard.press('Escape');
  await page.getByRole('dialog').waitFor({ state: 'hidden' });
  await page.setViewportSize({ width: 320, height: 760 });
  if (!await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    throw new Error('Overflow 320px');
  const violations = await page.evaluate(() => {
    const resources = performance.getEntriesByType('resource');
    return resources.filter(item => new URL(item.name).origin !== location.origin).map(item => item.name);
  });
  const csp = await page.evaluate(() => window.__shadeCspViolations);
  if (csp.length) throw new Error('CSP: ' + JSON.stringify(csp));
  if (errors.length || external.length || violations.length)
    throw new Error(JSON.stringify({ errors, external, violations }));
  return { result: 'TASK08_BROWSER_PASS', same_origin: true, javascript_errors: 0,
    external_requests: 0, real_core: true, synthetic_data: true, viewport: 320 };
}
