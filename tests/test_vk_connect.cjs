const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('website/static/vk-connect.js', 'utf8');

async function run({ query, auth, reject = false, api = { response: { upload_url: 'https://upload.example.test/' } }, apiReject = false,
  savedPhoto = [{ owner_id: -242059739, id: 123 }],
  wallPhotos = [{type: 'photo', photo: {owner_id: 21432243, id: 457248089}}] }) {
  const elements = Object.fromEntries(['connect', 'upload', 'verify', 'editor', 'status', 'result', 'token', 'copy'].map(id => [id, {
    disabled: true, hidden: true, value: '', textContent: '', type: 'password',
    handlers: {}, addEventListener(event, handler) { this.handlers[event] = handler; },
    focus() {}, select() {},
  }]));
  const calls = [];
  const uploads = [];
  const listeners = {};
  const window = {
    location: { search: query },
    addEventListener(event, handler) { listeners[event] = handler; },
    vkBridge: {
      isEmbedded: () => true,
      async send(method, params) {
        calls.push({ method, params });
        if (method === 'VKWebAppGetAuthToken') {
          if (reject) throw { error_type: 'api_error', error_data: { error_code: 15, access_token: 'SECRET' } };
          return auth;
        }
        if (method === 'VKWebAppCallAPIMethod') {
          if (apiReject) throw { error_type: 'api_error', error_data: { error_code: 5, request_params: [{ value: 'SECRET' }] } };
          if (params.method === 'photos.saveWallPhoto') return { response: savedPhoto };
          if (params.method === 'photos.getById') return { response: params.params.photos === '21432243_457248089'
            ? [{ owner_id: 21432243, id: 457248089, access_key: 'PRIVATE' }] : [{ owner_id: -242059739, id: 123 }] };
          if (params.method === 'wall.getById') return { response: [{ owner_id: -242059739, id: 11,
            attachments: wallPhotos }] };
          return api;
        }
        return {};
      },
    },
  };
  vm.runInNewContext(source, { window, URLSearchParams, document: { getElementById: id => elements[id] },
    fetch: async (url, options) => {
      if (!options) return { ok: true, json: async () => ({text: 'Prepared text with link'}) };
      uploads.push({url, options});
      return { ok: true, json: async () => ({photo: 'receipt', server: 123, hash: 'hash'}) };
    },
  });
  await new Promise(resolve => setImmediate(resolve));
  return { elements, calls, listeners, uploads };
}

(async () => {
  const outside = await run({ query: '' });
  assert.equal(outside.elements.connect.disabled, true);
  assert.equal(outside.calls.length, 0);
  const wrongApp = await run({ query: '?vk_app_id=123&vk_user_id=456' });
  assert.equal(wrongApp.calls.length, 0);

  const query = '?vk_app_id=54807565&vk_user_id=456';
  const ok = await run({ query, auth: { access_token: 'SECRET', scope: 'photos' } });
  // Loading the app must not request permissions automatically.
  assert.equal(ok.calls.length, 1);
  await ok.elements.connect.handlers.click();
  assert.equal(ok.calls[1].method, 'VKWebAppGetAuthToken');
  assert.equal(ok.calls[1].params.scope, 'photos');
  assert.equal(ok.calls.length, 3);
  assert.equal(ok.calls[2].method, 'VKWebAppCallAPIMethod');
  assert.equal(ok.calls[2].params.method, 'photos.getWallUploadServer');
  assert.equal(ok.calls[2].params.params.group_id, 242059739);
  assert.equal(ok.calls[2].params.params.access_token, 'SECRET');
  assert.ok(ok.elements.status.textContent.includes('Проверка пройдена'));
  assert.equal(ok.elements.token.value, '');
  assert.ok(!ok.elements.status.textContent.includes('SECRET'));
  ok.listeners.pagehide();
  assert.equal(ok.elements.token.value, '');

  const noPhotos = await run({ query, auth: { access_token: 'SECRET', scope: 'friends' } });
  await noPhotos.elements.connect.handlers.click();
  assert.equal(noPhotos.elements.result.hidden, true);
  assert.equal(noPhotos.elements.token.value, '');
  const denied = await run({ query, reject: true });
  await denied.elements.connect.handlers.click();
  assert.ok(denied.elements.status.textContent.includes('15'));
  assert.ok(!denied.elements.status.textContent.includes('SECRET'));
  const apiDenied = await run({ query, auth: { access_token: 'SECRET', scope: 'photos' }, apiReject: true });
  await apiDenied.elements.connect.handlers.click();
  assert.ok(apiDenied.elements.status.textContent.includes('код 5'));
  assert.ok(!apiDenied.elements.status.textContent.includes('SECRET'));
  const errorResponse = await run({ query, auth: { access_token: 'SECRET', scope: 'photos' }, api: { error: { error_code: 15 } } });
  await errorResponse.elements.connect.handlers.click();
  assert.ok(errorResponse.elements.status.textContent.includes('код 15'));
  const empty = await run({ query, auth: { access_token: 'SECRET', scope: 'photos' }, api: { response: {} } });
  await empty.elements.connect.handlers.click();
  assert.ok(empty.elements.status.textContent.includes('без адреса'));
  const saved = await run({ query, auth: { access_token: 'SECRET', scope: 'photos' } });
  await saved.elements.upload.handlers.click();
  assert.ok(saved.elements.status.textContent.includes('photo-242059739_123'));
  assert.equal(saved.uploads.length, 1);
  assert.ok(!saved.uploads[0].options.body.includes('SECRET'));
  assert.equal(saved.uploads[0].url, '/api/vk/poster-check');
  assert.equal(saved.calls.filter(c => c.method === 'VKWebAppCallAPIMethod').map(c => c.params.method).join(','),
    'photos.getWallUploadServer,photos.saveWallPhoto,photos.getById');
  assert.ok(!saved.elements.status.textContent.includes('SECRET'));
  const stringIds = await run({ query, auth: { access_token: 'SECRET', scope: 'photos' }, savedPhoto: [{ owner_id: '-242059739', id: '123' }] });
  await stringIds.elements.upload.handlers.click();
  assert.ok(stringIds.elements.status.textContent.includes('Постер сохранён'));
  const wrongOwner = await run({ query, auth: { access_token: 'SECRET', scope: 'photos' }, savedPhoto: [{ owner_id: 456, id: 123, access_key: 'SECRET' }] });
  await wrongOwner.elements.upload.handlers.click();
  assert.ok(wrongOwner.elements.status.textContent.includes('владелец: 456'));
  assert.ok(!wrongOwner.elements.status.textContent.includes('SECRET'));
  assert.ok(!wrongOwner.calls.some(c => c.params?.method === 'photos.getById'));
  const readback = await run({ query, auth: { access_token: 'SECRET', scope: 'photos' } });
  await readback.elements.verify.handlers.click();
  assert.ok(readback.elements.status.textContent.includes('Идентификатор исходного постера совпал'));
  assert.equal(readback.uploads.length, 0);
  assert.ok(!readback.calls.some(c => c.params?.method === 'wall.post'));
  const copied = await run({query, auth: {access_token: 'SECRET', scope: 'photos'},
    wallPhotos: [{type:'photo', photo:{owner_id:-242059739, id:999}}]});
  await copied.elements.verify.handlers.click();
  assert.ok(copied.elements.status.textContent.includes('содержит фотографий: 1'));
  assert.ok(copied.elements.status.textContent.includes('photo-242059739_999'));
  assert.ok(copied.elements.status.textContent.includes('Идентификаторы отличаются'));
  assert.equal(copied.uploads.length, 0);
  const noAttachment = await run({query, auth: {access_token:'SECRET', scope:'photos'}, wallPhotos:[]});
  await noAttachment.elements.verify.handlers.click();
  assert.ok(noAttachment.elements.status.textContent.includes('без вложений типа photo'));
  const compose = await run({ query, auth: { access_token: 'SECRET', scope: 'photos' } });
  await compose.elements.editor.handlers.click();
  const dialog = compose.calls.find(c => c.method === 'VKWebAppShowWallPostBox');
  assert.equal(dialog.params.owner_id, -242059739);
  assert.equal(dialog.params.attachments, 'photo21432243_457248089_PRIVATE');
  assert.ok(!compose.elements.status.textContent.includes('PRIVATE'));
  assert.equal(compose.uploads.length, 0);
  console.log('VK Bridge diagnostics passed: correct wall/group, no publishing, no token disclosure, denied and empty results.');
})();
