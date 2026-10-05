const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../website/static/site.js'), 'utf8');

function setup(id = '113425218') {
  const events = [];
  const handlers = {};
  const window = { ym: (...args) => events.push(args) };
  const document = {
    body: { dataset: { metrikaId: id, botUrl: 'https://t.me/kinojdun_bot', channelUrl: 'https://t.me/kinojdun_channel' } },
    querySelectorAll: () => [], querySelector: () => null,
    addEventListener: (name, handler) => { handlers[name] = handler; }
  };
  vm.runInNewContext(source, { document, window, URL });
  const click = (href, defaultPrevented = false) => handlers.click?.({
    target: { closest: () => ({ href }) }, defaultPrevented
  });
  return { events, window, click };
}

const tracking = setup();
tracking.click('https://t.me/kinojdun_bot');
tracking.click('https://t.me/kinojdun_bot?start=c_tv_123');
tracking.click('https://t.me/kinojdun_channel/42');
tracking.click('https://t.me/kinojdun_bot_fake');
tracking.click('https://example.com/kinojdun_bot');
tracking.click('https://t.me/kinojdun_bot', true);
assert.deepEqual(tracking.events.map(event => event[2]), ['bot_click', 'bot_click', 'watchlist_click', 'channel_click']);
assert.ok(tracking.events.every(event => event[0] === 113425218 && event[1] === 'reachGoal'));
delete tracking.window.ym;
assert.doesNotThrow(() => tracking.click('https://t.me/kinojdun_bot'));
assert.equal(tracking.events.length, 4);
const disabled = setup('');
disabled.click('https://t.me/kinojdun_bot');
assert.equal(disabled.events.length, 0);
console.log('Analytics navigation checks passed');
