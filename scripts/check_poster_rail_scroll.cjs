const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('C:/Users/cvet7/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{
  for(const width of [1920,1440,390]){
   const page=await browser.newPage({viewport:{width,height:1080}});
   if(!process.argv.includes('--production'))await page.route('**/static/site.css?*',r=>r.fulfill({contentType:'text/css',body:fs.readFileSync(path.resolve(__dirname,'../website/static/site.css'),'utf8')}));
   await page.goto('https://kinojdun.ru/',{waitUntil:'domcontentloaded'});
   const rail=page.locator('.poster-rail:has(.tracked-project)').first();
   await rail.scrollIntoViewIfNeeded();
   const check=async()=>{
    const state=await rail.evaluate(e=>({y:getComputedStyle(e).overflowY,x:getComputedStyle(e).overflowX,height:e.clientHeight,scrollHeight:e.scrollHeight,width:e.clientWidth,scrollWidth:e.scrollWidth}));
    assert.equal(state.y,'hidden');assert.equal(state.x,'auto');assert(state.scrollHeight<=state.height+1,'Vertical overflow remains');assert(state.scrollWidth>state.width,'Horizontal scrolling missing');return state;
   };
   await check();
   const dropdown=rail.locator('.tracked-bot-dropdown').first();
   const trigger=dropdown.locator('.bot-dropdown-trigger');
   await trigger.hover();await page.waitForTimeout(250);
   const menu=dropdown.locator('.bot-dropdown-menu');assert(await menu.isVisible());
   const mb=await menu.boundingBox(),tb=await trigger.boundingBox();assert(mb.y+mb.height<=tb.y,'Menu must open upward');
   assert(await menu.locator('a').first().evaluate(e=>{const b=e.getBoundingClientRect();return e.contains(document.elementFromPoint(b.x+b.width/2,b.y+b.height/2));}),'Menu is clipped');
   await menu.hover();await page.waitForTimeout(250);assert.equal(await trigger.getAttribute('aria-expanded'),'true','Menu closes when pointer crosses gap');
   await check();await page.mouse.move(0,0);await page.locator('body').press('Escape');
   await rail.evaluate(e=>e.scrollLeft=e.scrollWidth);await check();
   await rail.locator('.tracked-bot-dropdown').last().locator('.bot-dropdown-trigger').focus();await page.keyboard.press('ArrowDown');await page.waitForTimeout(250);await check();
   const lastLink=rail.locator('.tracked-bot-dropdown').last().locator('.bot-dropdown-menu a').first();
   assert(await lastLink.evaluate(e=>{const b=e.getBoundingClientRect();return e.contains(document.elementFromPoint(b.x+b.width/2,b.y+b.height/2));}),'Last menu clipped');
   await page.screenshot({path:path.resolve(__dirname,`../diagnostics/hero-demo/rail-${width}.png`)});
   console.log('Horizontal rail and upward subscription menu passed: '+width);await page.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
