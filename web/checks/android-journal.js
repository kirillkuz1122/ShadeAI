async (page) => {
  const expected = __EVENT__;
  const check = (value, message) => { if (!value) throw new Error(message); };
  const errors = [], external = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (!["127.0.0.1", "localhost"].includes(new URL(request.url()).hostname)) external.push(request.url());
  });
  await page.setViewportSize({width: 1440, height: 1000});
  await page.goto("http://127.0.0.1:5173");
  const key = page.getByLabel("API-ключ Shade");
  if (!await key.isVisible()) await page.getByText("Подключение к Core", {exact:false}).first().click();
  await key.fill("task09-core-emulator-key-00000000000");
  await page.getByRole("button", {name:"Сохранить ключ", exact:true}).click();
  const row = page.getByRole("button", {name:"Открыть уведомление: " + expected.title, exact:true});
  await row.waitFor();
  check(await row.locator("time").getAttribute("datetime") === expected.timestamp, "Время Android/Core/Web различается");
  await row.click();
  const dialog = page.getByRole("dialog");
  await dialog.getByText(expected.uuid, {exact:true}).waitFor();
  check(await dialog.locator(".notification-text").innerText() === expected.text, "Текст Android/Core/Web различается");
  await dialog.getByText("Идентификатор события", {exact:true}).waitFor();
  await page.screenshot({path:"output/playwright/task13-web-desktop.png"});
  await page.setViewportSize({width:320,height:740});
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Overflow страницы при 320px");
  check(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth), "UUID не помещается в диалог при 320px");
  await page.screenshot({path:"output/playwright/task13-web-mobile.png"});
  await page.keyboard.press("Escape");
  await dialog.waitFor({state:"hidden"});
  await page.reload();
  await row.waitFor();
  check(await page.locator(".notification-row").count() === 2, "История должна содержать две записи AVD");
  check(errors.length === 0, "Ошибки JavaScript: " + errors.join("; "));
  check(external.length === 0, "Внешние запросы: " + external.join("; "));
  return "PASS: Android/Core SQLite/Web — одинаковые UUID, текст и время; restart без дубля, 320px/Escape, без внешних запросов и JS-ошибок";
}
