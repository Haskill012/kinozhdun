const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { chromium } = require('C:/Users/cvet7/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'diagnostics/bot-dropdown');
(async () => {
  const browser = await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe', headless:true});
  try {
    for (const mobile of [false, true]) {
      const page = await browser.newPage({viewport: mobile ? {width:390,height:844} : {width:1440,height:1000}, hasTouch:mobile, isMobile:mobile});
      const errors=[]; page.on('pageerror', e=>errors.push(e.message));
      if (process.argv.includes('--production')) await page.goto('https://kinojdun.ru', {waitUntil:'domcontentloaded'});
      else {
        let html=fs.readFileSync(path.join(out,'home.html'),'utf8');
        html=html.replace(/<link rel="stylesheet"[^>]+>/,'<style>'+fs.readFileSync(path.join(root,'website/static/site.css'),'utf8')+'</style>');
        html=html.replace(/<script src="\/static\/site.js[^>]+><\/script>/,'');
        await page.setContent(html);
        await page.addScriptTag({content:fs.readFileSync(path.join(root,'website/static/site.js'),'utf8')});
      }
      const wrapper=page.locator('.header-bot-dropdown');
      const trigger=wrapper.locator('button');
      const menu=wrapper.locator('.bot-dropdown-menu');
      assert.equal(await trigger.getAttribute('aria-expanded'),'false');
      if (mobile) await trigger.tap(); else await trigger.hover();
      await page.waitForTimeout(250);
      assert.equal(await trigger.getAttribute('aria-expanded'),'true');
      assert.equal(await menu.evaluate(e=>getComputedStyle(e).visibility),'visible');
      assert.match(await menu.locator('.bot-dropdown-max').getAttribute('href'), /^https:\/\/max.ru\/id5001170357_1_bot/);
      const box=await menu.boundingBox(); assert(box.x>=0 && box.x+box.width <= (mobile?390:1440));
      await page.screenshot({path:path.join(out,mobile?'mobile.png':'desktop.png')});
      if (mobile) {
        await trigger.tap(); assert.equal(await trigger.getAttribute('aria-expanded'),'false');
        await trigger.tap(); await page.locator('h1').first().tap();
        assert.equal(await trigger.getAttribute('aria-expanded'),'false');
      } else {
        await trigger.focus(); await page.keyboard.press('Escape');
        assert.equal(await trigger.getAttribute('aria-expanded'),'false');
        await page.waitForTimeout(250);
        assert.equal(await menu.evaluate(e=>getComputedStyle(e).visibility),'hidden');
        await page.keyboard.press('ArrowDown');
        assert.equal(await menu.locator('a').first().evaluate(e=>e===document.activeElement),true);
        await page.keyboard.press('Tab');
        assert.equal(await menu.locator('.bot-dropdown-max').evaluate(e=>e===document.activeElement),true);
        await page.keyboard.press('Tab');
        assert.equal(await menu.locator('.bot-dropdown-vk').evaluate(e=>e===document.activeElement),true);
        await page.keyboard.press('Escape');
      }
      const hero=page.locator('.spotlight-bot-dropdown').first();
      if(await hero.count()) {
        if(mobile) await hero.locator('button').tap(); else await hero.locator('button').hover();
        await page.waitForTimeout(250);
        const max=hero.locator('.bot-dropdown-max');
        assert.match(await max.getAttribute('href'),/\?start=c_(movie|tv)_\d+/);
        await page.screenshot({path:path.join(out,mobile?'mobile-hero.png':'desktop-hero.png')});
        assert(await max.evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}));
        const vk=hero.locator('.bot-dropdown-vk');
        assert.match(await vk.getAttribute('href'),/\?ref=c_(movie|tv)_\d+/);
        assert(await vk.evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}));
      }
      assert.deepEqual(errors,[]);
      console.log(mobile?'Mobile: passed':'Desktop: passed');
      await page.close();
    }
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
