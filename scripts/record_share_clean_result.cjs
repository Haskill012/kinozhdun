const fs=require('node:fs'),path=require('node:path');
const {chromium}=require('C:/Users/cvet7/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const out=path.resolve(__dirname,'../diagnostics/hero-demo/telegram-share/clean-result');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const context=await chromium.launchPersistentContext(path.resolve(out,'../../browser-profile'),{executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:false,viewport:{width:1280,height:800},recordVideo:{dir:out,size:{width:1280,height:800}},args:['--disable-notifications']});
 const page=context.pages()[0]||await context.newPage();const start=Date.now();
 try{
  await page.goto('https://web.telegram.org/a/',{waitUntil:'domcontentloaded'});
  await page.getByText('Saved Messages',{exact:true}).and(page.locator(':visible')).first().click();await page.waitForTimeout(1800);
  await page.mouse.move(1170,760);await page.waitForTimeout(700);
  const time=(Date.now()-start)/1000;
  await page.screenshot({path:path.join(out,'result.png')});await page.waitForTimeout(4200);
  const video=page.video();await context.close();
  fs.writeFileSync(path.join(out,'capture.json'),JSON.stringify({source:await video.path(),start:time},null,2));
  console.log('Clean final card recorded without hover reaction.');
 }catch(e){await page.screenshot({path:path.join(out,'error.png')});await context.close();throw e;}
})().catch(e=>{console.error(e);process.exitCode=1;});
