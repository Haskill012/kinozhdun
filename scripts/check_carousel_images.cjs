const fs=require('fs');
const path=require('path');
const assert=require('assert/strict');
const {chromium}=require('C:/Users/cvet7/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..');
const out=path.join(root,'diagnostics/carousel-images');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{
  for(const mobile of [false,true]){
   const page=await browser.newPage({viewport:mobile?{width:390,height:1000}:{width:1440,height:1000},isMobile:mobile,hasTouch:mobile});
   const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.goto('https://kinojdun.ru',{waitUntil:'domcontentloaded'});
   if(!process.argv.includes('--production')){
    await page.addStyleTag({content:fs.readFileSync(path.join(root,'website/static/site.css'),'utf8')});
    await page.locator('.spotlight-slide').evaluateAll(slides=>slides.forEach(slide=>{
     const img=slide.querySelector(':scope > .spotlight-image');
     if(img){const art=document.createElement('div');art.className='spotlight-art';img.replaceWith(art);art.append(img);}
    }));
   }
   const hero=page.locator('.dynamic-spotlight');
   await hero.scrollIntoViewIfNeeded();
   await hero.locator('.spotlight-pause').click();
   const dots=hero.locator('[data-go]');const count=await dots.count();
   for(let i=0;i<count;i++){
    await dots.nth(i).click();await page.waitForTimeout(750);
    const slide=hero.locator(`[data-slide="${i}"]`);
    const img=slide.locator('.spotlight-image');
    await img.evaluate(e=>e.decode());
    const layers=await slide.evaluate(e=>{
     const art=e.querySelector('.spotlight-art');const image=e.querySelector('.spotlight-image');
     const box=art.getBoundingClientRect();const items=document.elementsFromPoint(box.x+box.width*.85,box.y+box.height*.4);
     return {loaded:image.naturalWidth>0,above:items.indexOf(image)>=0 && items.indexOf(image)<items.indexOf(e),overflow:getComputedStyle(art).overflow,z:getComputedStyle(art).zIndex,items:items.map(x=>x.className),rect:box.toJSON()};
    });
    assert(layers.loaded && layers.above,JSON.stringify({slide:i,layers}));
    assert.equal(layers.overflow,'hidden');
    assert.equal(layers.z,'0');
    if(i===0 || i===1)await page.screenshot({path:path.join(out,`${mobile?'mobile':'desktop'}-slide-${i}.png`)});
    const trigger=slide.locator('.bot-dropdown-trigger');
    if(mobile)await trigger.tap();else await trigger.hover();
    await page.waitForTimeout(250);
    const vk=slide.locator('.bot-dropdown-vk');
    await vk.scrollIntoViewIfNeeded();
    assert(await vk.evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}));
    await trigger.press('Escape');
   }
   // Rapid navigation must settle on the final requested slide.
   await dots.nth(0).click();await dots.nth(count-1).click();await page.waitForTimeout(800);
   assert.equal(await hero.locator('.spotlight-slide:not([hidden])').count(),1);
   assert.deepEqual(errors,[]);
   console.log(`${mobile?'Mobile':'Desktop'}: ${count} loaded images above background; menus and transitions passed`);
   await page.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
