// Genuine Telegram UI footage. Commands are chosen after inspecting each state.
const fs=require('node:fs'),path=require('node:path');
const {chromium}=require('C:/Users/cvet7/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const out=path.resolve(__dirname,'../diagnostics/hero-demo/telegram-share');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const context=await chromium.launchPersistentContext(path.resolve(out,'../browser-profile'),{executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:false,viewport:{width:1280,height:800},recordVideo:{dir:out,size:{width:1280,height:800}},args:['--disable-notifications']});
 const page=context.pages()[0]||await context.newPage();const start=Date.now(),events=[];
 await page.goto('https://web.telegram.org/a/',{waitUntil:'domcontentloaded'});
 await page.getByText('КиноЖдун Бот',{exact:false}).first().click();
 await page.waitForTimeout(1400);
 const editor=()=>page.locator('#MiddleColumn [contenteditable=true]:visible').last();
 await editor().fill('/list');await editor().press('Enter');await page.waitForTimeout(2200);
 await page.screenshot({path:path.join(out,'initial.png')});
 await page.evaluate(()=>{const p=document.createElement('div');p.id='demo-pointer';p.style='position:fixed;left:1000px;top:700px;width:34px;height:44px;pointer-events:none;z-index:2147483647;filter:drop-shadow(0 1px 2px #0008)';p.innerHTML='<svg viewBox="0 0 34 44"><path d="M2 2v30l8-7 8 15 8-4-7-13 12-2Z" fill="white" stroke="#111" stroke-width="2"/></svg>';document.body.append(p);});
 let x=1000,y=700;
 const click=async(selector,label)=>{
  const loc=page.locator(selector).last();await loc.scrollIntoViewIfNeeded();await page.waitForTimeout(450);const b=await loc.boundingBox();if(!b)throw Error('Missing target');
  const nx=b.x+b.width/2,ny=b.y+b.height/2;
  events.push({label,time:(Date.now()-start)/1000,x:nx,y:ny});
  for(let i=1;i<=24;i++){const a=i/24,e=a*a*(3-2*a);await page.mouse.move(x+(nx-x)*e,y+(ny-y)*e);await page.evaluate(({x,y})=>{const p=document.querySelector('#demo-pointer');p.style.left=x+'px';p.style.top=y+'px';},{x:x+(nx-x)*e,y:y+(ny-y)*e});await page.waitForTimeout(20);}
  x=nx;y=ny;await page.evaluate(({x,y})=>{const r=document.createElement('div');r.style=`position:fixed;left:${x-14}px;top:${y-14}px;width:28px;height:28px;border:3px solid #d4fa58;border-radius:50%;background:#d4fa5830;z-index:2147483646;pointer-events:none`;document.body.append(r);r.animate([{transform:'scale(1)',opacity:1},{transform:'scale(3.4)',opacity:0}],{duration:550}).finished.then(()=>r.remove());},{x,y});await page.mouse.click(nx,ny);await page.waitForTimeout(1200);
 };
 let last=fs.existsSync(path.join(out,'command.json'))?JSON.parse(fs.readFileSync(path.join(out,'command.json'))).id:null;
 await page.locator('#MiddleColumn button:has-text("Поделиться списком")').last().scrollIntoViewIfNeeded();
 await page.screenshot({path:path.join(out,'ready.png')});console.log('Share recording ready.');
 while(true){await page.waitForTimeout(250);const file=path.join(out,'command.json');if(!fs.existsSync(file))continue;const c=JSON.parse(fs.readFileSync(file));if(c.id===last)continue;last=c.id;
  try{
   if(c.action==='close'){const video=page.video();await context.close();fs.writeFileSync(path.join(out,'capture.json'),JSON.stringify({source:await video.path(),events},null,2));console.log('Share recording saved.');break;}
   if(c.action==='click')await click(c.selector,c.label);
   if(c.action==='fill'){await page.locator(c.selector).last().fill(c.text);await page.waitForTimeout(650);}
   if(c.action==='press')await page.locator(c.selector).last().press(c.key);
   if(c.action==='reveal'){await page.locator(c.selector).last().scrollIntoViewIfNeeded();await page.waitForTimeout(600);}
   if(c.wait)await page.waitForTimeout(c.wait);
   const name=c.label||'state';await page.screenshot({path:path.join(out,name+'.png')});
   fs.writeFileSync(path.join(out,name+'.txt'),await page.locator('#MiddleColumn').innerText());
   const elements=await page.locator(c.inspect||'#MiddleColumn [class*=InlineBot],.Modal input').evaluateAll(es=>es.map(e=>({tag:e.tagName,text:e.textContent,className:e.className})));
   fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({id:last,ok:true,events,elements}));
  }catch(e){fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({id:last,ok:false,error:e.message}));}
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
