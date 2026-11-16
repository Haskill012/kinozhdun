const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium} = require('C:/Users/cvet7/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const out = path.resolve(__dirname, '../diagnostics/hero-demo');
const base = process.argv.includes('--production') ? 'https://kinojdun.ru' : (process.env.DEMO_BASE || 'http://127.0.0.1:8100');
(async () => {
  const browser = await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
  try {
    for (const width of [1440, 650, 390]) {
      const page = await browser.newPage({viewport:{width,height:1000}});
      const errors=[]; page.on('pageerror',e=>errors.push(e.message));
      await page.goto(base+'/',{waitUntil:'domcontentloaded'});
      const video=page.locator('.subscription-demo-video').first();
      await page.waitForFunction(()=>document.querySelector('.subscription-demo-video').currentTime>0);
      await video.evaluate(e=>{e.currentTime=0;});
      assert.equal(await page.locator('[data-slide]').count(),6);
      assert.equal(await page.locator('h1').count(),1);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      const bottom=await page.locator('.demo-screen').first().boundingBox();
      const controls=await page.locator('.spotlight-controls').boundingBox();
      await page.screenshot({path:path.join(out,'hero-'+width+'.png')});
      console.log(JSON.stringify({width,video:bottom,controls}));
      assert(bottom.y+bottom.height < controls.y, 'Video overlaps carousel controls at '+width);
      assert.equal(await page.locator('.subscription-demo-video').count(),3);
      await page.locator('[data-go="1"]').click();
      const second=page.locator('[data-slide="1"] video');
      await page.waitForFunction(()=>document.querySelector('[data-slide="1"] video').currentTime>0);
      await page.waitForTimeout(750);
      assert.equal(await video.evaluate(e=>e.paused),true);
      const secondBox=await page.locator('[data-slide="1"] .demo-screen').boundingBox();
      assert(secondBox.y+secondBox.height < controls.y,'Second video overlaps controls');
      await page.screenshot({path:path.join(out,'telegram-hero-'+width+'.png')});
      await second.evaluate(e=>e.pause());await page.waitForTimeout(250);
      assert.equal(await second.evaluate(e=>e.paused),true,'Second native pause overridden');
      await page.locator('[data-go="2"]').click();
      assert.equal(await second.evaluate(e=>e.paused),true);
      const third=page.locator('[data-slide="2"] video');
      await page.waitForFunction(()=>document.querySelector('[data-slide="2"] video').currentTime>0);
      await page.waitForTimeout(750);
      const thirdBox=await page.locator('[data-slide="2"] .demo-screen').boundingBox();
      assert(thirdBox.y+thirdBox.height<controls.y,'Third video overlaps controls');
      await page.screenshot({path:path.join(out,'share-hero-'+width+'.png')});
      await third.evaluate(e=>e.pause());await page.waitForTimeout(250);
      assert.equal(await third.evaluate(e=>e.paused),true,'Third native pause overridden');
      await page.locator('[data-go="1"]').click();
      assert.equal(await third.evaluate(e=>e.paused),true,'Hidden third video plays');
      assert(await second.evaluate(e=>e.currentTime<2),'Second recording does not restart');
      await page.locator('[data-go="0"]').click();
      if(width===1440){
        await page.waitForTimeout(7500);
        assert.equal(await page.locator('[data-slide="0"]').isVisible(),true,'Intro advances before recording ends');
        await video.evaluate(e=>e.pause());
        await page.mouse.move(10,10);await page.waitForTimeout(200);
        assert.equal(await video.evaluate(e=>e.paused),true,'Native pause is overridden');
        await page.locator('[data-go="1"]').click();
        assert.equal(await video.evaluate(e=>e.paused),true,'Hidden video keeps playing');
        await page.locator('[data-go="0"]').click();
        assert(await video.evaluate(e=>e.currentTime<2),'Returning intro does not restart');
        await page.mouse.move(10,10);await page.locator('body').click({position:{x:10,y:10}});
        await video.evaluate(e=>{e.currentTime=e.duration-.3;e.play();});
        await page.waitForFunction(()=>document.querySelector('[data-slide="1"]').getAttribute('aria-hidden')==='false',{},{timeout:15000}).catch(async error=>{
          console.log(await page.evaluate(()=>({scroll:scrollY,focus:document.activeElement?.tagName,hidden:document.hidden,paused:document.querySelector('.dynamic-spotlight').dataset.motionPaused,video:[...document.querySelectorAll('video')].map(v=>({time:v.currentTime,duration:v.duration,ended:v.ended,paused:v.paused,ready:v.readyState})),slides:[...document.querySelectorAll('[data-slide]')].map(s=>({index:s.dataset.slide,hidden:s.hidden}))})));
          throw error;
        });
        assert.equal(await page.locator('[data-slide="1"]').isVisible(),true,'Completed recording does not advance');
        await second.evaluate(e=>{e.currentTime=e.duration-.3;e.play();});
        await page.waitForFunction(()=>document.querySelector('[data-slide="2"]').getAttribute('aria-hidden')==='false',{},{timeout:15000});
        assert.equal(await page.locator('[data-slide="2"]').isVisible(),true,'Second recording does not advance');
        assert.equal(await video.evaluate(e=>e.paused),true);
        await third.evaluate(e=>{e.currentTime=e.duration-.3;e.play();});
        await page.waitForFunction(()=>document.querySelector('[data-slide="3"]').getAttribute('aria-hidden')==='false',{},{timeout:15000});
        assert.equal(await page.locator('[data-slide="3"]').isVisible(),true,'Third recording does not advance');
      }
      await page.emulateMedia({reducedMotion:'reduce'});
      await page.reload({waitUntil:'domcontentloaded'});
      await page.waitForSelector('.spotlight-controls:not([hidden])');
      assert.equal(await video.evaluate(e=>e.paused),true,'Reduced motion starts autoplay');
      assert.equal(await page.locator('.subscription-demo-video').nth(1).evaluate(e=>e.paused),true);
      assert.equal(await page.locator('.subscription-demo-video').nth(2).evaluate(e=>e.paused),true);
      await page.goto(base+'/how-to-subscribe',{waitUntil:'domcontentloaded'});
      assert.equal(await page.locator('video').count(),1);
      assert.equal(await page.locator('video').evaluate(e=>e.paused),true);
      if(process.argv.includes('--production')) {
        await page.goto(base+'/how-to-subscribe?project=movie:1294189',{waitUntil:'domcontentloaded'});
        assert.match(await page.locator('.subscription-guide .bot-dropdown-tg').getAttribute('href'),/start=c_movie_1294189/);
      }
      assert.deepEqual(errors,[]);
      console.log('Video, layout and guide passed: '+width+'px');
      await page.close();
    }
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
