async (page) => {
  const check = (value, message) => { if (!value) throw new Error(message); };
  const errors = [], external = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (!/^(127\.0\.0\.1|localhost)$/.test(new URL(request.url()).hostname)) external.push(request.url());
  });
  await page.goto("http://127.0.0.1:5173");
  await page.getByLabel("API-ключ Shade").fill("task07-browser-test-key-000000000");
  await page.getByRole("button", { name: "Сохранить ключ" }).click();
  await page.getByText("1–20 из 45", { exact: true }).waitFor();
  let phase = "processing", errorCode = "PROCESSOR_ERROR";
  await page.route("**/api/v1/notifications/45", async route => {
    const response = await route.fetch();
    const original = await response.json();
    await route.fulfill({ json: { ...original,
      status: phase === "processed" ? "processed" : "stored",
      processing_status: phase, processing_attempts: 1,
      processing_error_code: phase === "failed" ? errorCode : null,
      processed_data: phase === "processed" ? { processor: "diagnostic", llm: false } : null,
    }});
  });
  await page.locator(".notification-row").first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByText("Обрабатывается", { exact: true }).waitFor();
  phase = "failed";
  await dialog.getByText("Ошибка обработки", { exact: true }).waitFor();
  await dialog.getByText("Обработчик завершился с ошибкой", { exact: true }).waitFor();
  errorCode = "untrusted-private-unknown-code";
  await dialog.getByText("Не удалось обработать запись", { exact: true }).waitFor();
  check(!(await dialog.innerText()).includes(errorCode), "Неизвестный код не попал в текст UI");
  phase = "processed";
  await dialog.getByText("Проверка очереди завершена", { exact: true }).waitFor();
  await dialog.getByText("Проверен конвейер очереди. Анализ текста и LLM не выполнялись.", { exact: true }).waitFor();
  await page.setViewportSize({ width: 320, height: 780 });
  check(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth), "Запись помещается при 320px");
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Нет горизонтального overflow");
  await page.screenshot({ path: "output/playwright/task15-processing.png" });
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "hidden" });
  await page.unroute("**/api/v1/notifications/45");
  check(errors.length === 0, "Нет JS-ошибок: " + errors.join(","));
  check(external.length === 0, "Нет внешних запросов");
  return { result: "PASS", check: "TASK-15 processing/failed/diagnostic/auto-refresh/320px", errors, external };
}
