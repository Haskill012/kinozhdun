// Real browser capture. Cursor and click rings are annotation overlays only.
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('C:/Users/cvet7/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const out=path.resolve(__dirname,'../diagnostics/hero-demo/v2');
fs.mkdirSync(out,{recursive:true});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1280,height:1000},recordVideo:{dir:out,size:{width:1280,height:1000}}});
 const page=await context.newPage();
 await page.addInitScript(()=>{
   const install=()=>{
     const style=document.createElement('style');
     style.textContent='.demo-pointer{position:fixed;width:28px;height:34px;z-index:2147483647;pointer-events:none;filter:drop-shadow(0 2px 3px #0008)}.demo-click{position:fixed;width:18px;height:18px;border:3px solid #d4fa58;background:#d4fa5820;border-radius:50%;z-index:2147483646;pointer-events:none;animation:demo-click .55s ease-out forwards}@keyframes demo-click{from{transform:translate(-50%,-50%) scale(.6);opacity:1}to{transform:translate(-50%,-50%) scale(3.5);opacity:0}}';
     document.head.append(style);
     const pointer=document.createElement('div');pointer.className='demo-pointer';
     pointer.innerHTML='<svg viewBox="0 0 28 34"><path d="M2 2L2 27L9 21L15 32L21 29L15 19L25 18Z" fill="white" stroke="#111312" stroke-width="2" stroke-linejoin="round"/></svg>';
     document.body.append(pointer);
     document.addEventListener('mousemove',e=>{pointer.style.left=e.clientX+'px';pointer.style.top=e.clientY+'px';},{passive:true});
     document.addEventListener('mousedown',e=>{const ring=document.createElement('div');ring.className='demo-click';ring.style.left=e.clientX+'px';ring.style.top=e.clientY+'px';document.body.append(ring);setTimeout(()=>ring.remove(),650);},true);
   };
   document.addEventListener('DOMContentLoaded',install,{once:true});
 });
 const events=[];let position={x:950,y:250};
 const move=async(selector)=>{
   const locator=page.locator(selector).first();await locator.waitFor({state:'visible'});
   const box=await locator.boundingBox();const target={x:box.x+box.width*.5,y:box.y+box.height*.5};
   // Fail rather than scrolling a control into view.
   if(box.y<0||box.y+box.height>1000)throw Error('Target requires scrolling: '+selector);
   for(let i=1;i<=24;i++){const t=i/24,e=t*t*(3-2*t);await page.mouse.move(position.x+(target.x-position.x)*e,position.y+(target.y-position.y)*e);await sleep(16);}
   position=target;return target;
 };
 const click=async(selector,label)=>{const target=await move(selector);events.push({label,action:'click',at:Date.now(),...target});await page.mouse.down();await sleep(80);await page.mouse.up();};
 await page.goto('https://kinojdun.ru/catalog',{waitUntil:'domcontentloaded'});
 await page.locator('.site-search input').waitFor();
 await page.screenshot({path:path.join(out,'initial.png')});
 events.push({label:'begin',at:Date.now()});
 await click('.site-search input','search');
 await page.locator('.site-search input').pressSequentially('Мангуст',{delay:95});
 await page.locator('.site-search-result[href="/title/movie/1294189"]').waitFor({state:'visible'});
 await sleep(500);
 await click('.site-search-result[href="/title/movie/1294189"]','choose-film');
 await page.waitForURL('**/title/movie/1294189');
 await page.locator('.project-hero-dropdown .bot-dropdown-trigger').waitFor({state:'visible'});
 await page.screenshot({path:path.join(out,'film.png')});
 await sleep(500);
 await move('.project-hero-dropdown .bot-dropdown-trigger');
 events.push({label:'open-menu',at:Date.now(),...position});
 await sleep(550);
 await page.screenshot({path:path.join(out,'menu.png')});
 await click('.project-hero-dropdown .bot-dropdown-tg','telegram');
 await sleep(700);
 events.push({label:'end',at:Date.now()});
 const video=await page.video().path();await context.close();await browser.close();
 fs.writeFileSync(path.join(out,'capture.json'),JSON.stringify({source:video,events},null,2));
 console.log(JSON.stringify({source:video,events}));
})().catch(e=>{console.error(e);process.exitCode=1;});
