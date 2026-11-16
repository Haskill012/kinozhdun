const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('C:/Users/cvet7/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'diagnostics/hero-demo');
fs.mkdirSync(out, {recursive: true});
const commandFile = path.join(out, 'command.json');
const resultFile = path.join(out, 'result.json');
const recording = process.argv.includes('--record');
(async () => {
  const context = await chromium.launchPersistentContext(path.join(out, 'browser-profile'), {
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: false, viewport: {width: 1280, height: 800},
    ...(recording ? {recordVideo: {dir: path.join(out, 'raw'), size: {width: 1280, height: 800}}} : {}),
    args: ['--disable-notifications'],
  });
  let page = context.pages()[0] || await context.newPage();
  await page.goto(recording ? 'https://kinojdun.ru' : 'https://web.telegram.org/a/', {waitUntil: 'domcontentloaded'});
  console.log(recording ? 'Recording browser ready.' : 'Telegram Web ready for manual sign-in.');
  let lastId = fs.existsSync(commandFile) ? JSON.parse(fs.readFileSync(commandFile, 'utf8')).id : undefined;
  while (true) {
    await new Promise(resolve => setTimeout(resolve, 300));
    if (!fs.existsSync(commandFile)) continue;
    const command = JSON.parse(fs.readFileSync(commandFile, 'utf8'));
    if (command.id === lastId) continue;
    lastId = command.id;
    try {
      let result;
      if (command.action === 'inspect') {
        result = await Promise.all(context.pages().map(async p => ({url: p.url(), text: (await p.locator('body').innerText()).slice(0, 16000)})));
      } else if (command.action === 'goto') {
        await page.goto(command.url, {waitUntil: 'domcontentloaded'});
      } else if (command.action === 'hover') {
        await page.locator(command.selector).first().hover();
      } else if (command.action === 'click') {
        await page.locator(command.selector).first().click();
      } else if (command.action === 'fill') {
        await page.locator(command.selector).first().fill(command.text);
      } else if (command.action === 'scroll') {
        await page.mouse.wheel(0, command.y);
      } else if (command.action === 'press') {
        await page.locator(command.selector).first().press(command.key);
      } else if (command.action === 'elements') {
        result = await page.locator(command.selector).evaluateAll(elements => elements.map(e => ({tag: e.tagName, text: e.textContent, role: e.getAttribute('role'), className: e.className, href: e.getAttribute('href')})));
      } else if (command.action === 'selectPage') {
        page = context.pages().find(p => p.url().includes(command.urlPart));
        if (!page) throw new Error('Page not found');
        await page.bringToFront();
      } else if (command.action === 'screenshot') {
        await page.screenshot({path: path.join(out, command.name || 'browser.png')});
      } else if (command.action === 'links') {
        result = await page.locator(command.selector || 'a').evaluateAll(elements => elements.map(e => ({text: e.textContent, href: e.getAttribute('href')})));
      } else if (command.action === 'close') {
        await context.close();
        fs.writeFileSync(resultFile, JSON.stringify({id: lastId, ok: true}));
        break;
      } else throw new Error('Unknown action');
      fs.writeFileSync(resultFile, JSON.stringify({id: lastId, ok: true, result}));
      fs.appendFileSync(path.join(out, 'actions.jsonl'), JSON.stringify({id: lastId, time: Date.now(), action: command.action, selector: command.selector, result}) + '\n');
    } catch (error) {
      fs.writeFileSync(resultFile, JSON.stringify({id: lastId, ok: false, error: error.message}));
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
