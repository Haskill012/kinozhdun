const fs = require('node:fs');
const path = require('node:path');
const out = path.resolve(__dirname, '../diagnostics/hero-demo');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
(async () => {
  const commands = JSON.parse(fs.readFileSync(process.argv[2], 'utf8').replace(/^\uFEFF/, ''));
  for (const command of commands) {
    if (command.wait) { await sleep(command.wait); continue; }
    command.id = Date.now();
    fs.writeFileSync(path.join(out, 'command.json'), JSON.stringify(command));
    const deadline = Date.now() + 40000;
    while (true) {
      await sleep(200);
      let result;
      try { result = JSON.parse(fs.readFileSync(path.join(out, 'result.json'), 'utf8')); } catch {}
      if (result?.id === command.id) {
        console.log(JSON.stringify(result));
        if (!result.ok) throw new Error(result.error);
        break;
      }
      if (Date.now() > deadline) throw new Error('Browser command timed out: ' + command.action);
    }
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
