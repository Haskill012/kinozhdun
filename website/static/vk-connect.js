'use strict';
(() => {
  const APP_ID = 54807565;
  const GROUP_ID = 242059739;
  const button = document.getElementById('connect');
  const upload = document.getElementById('upload');
  const verify = document.getElementById('verify');
  const editor = document.getElementById('editor');
  const status = document.getElementById('status');
  const bridge = window.vkBridge;
  const params = new URLSearchParams(window.location.search);
  const setStatus = (message) => { status.textContent = message; };
  let token = '';
  const safeError = (error) => {
    const data = error?.error_data?.error || error?.error_data || error?.error || error;
    const code = Number(data?.error_code);
    const type = String(error?.error_type || 'api_error').replace(/[^a-z_]/gi, '').slice(0, 40);
    return `${type}${Number.isFinite(code) ? ', код ' + code : ''}`;
  };
  async function init() {
    if (!bridge || !params.get('vk_user_id') || Number(params.get('vk_app_id')) !== APP_ID || !bridge.isEmbedded()) {
      setStatus('Откройте приложение внутри ВК: https://vk.ru/app54807565.');
      return;
    }
    try {
      await bridge.send('VKWebAppInit');
      button.disabled = false;
      upload.disabled = false;
      verify.disabled = false;
      editor.disabled = false;
      setStatus('Готово. Проверка не создаёт постов и не загружает фотографии.');
    } catch (_) {
      setStatus('ВК не запустил приложение. Откройте его заново.');
    }
  }
  button.addEventListener('click', async () => {
    button.disabled = true;
    token = '';
    let stage = 'получение права photos';
    setStatus('Ожидаем разрешение ВК…');
    try {
      const data = await bridge.send('VKWebAppGetAuthToken', { app_id: APP_ID, scope: 'photos' });
      if (!data.access_token || !String(data.scope || '').split(/[\s,]+/).includes('photos')) {
        setStatus('ВК не предоставил право photos. Загрузка через мини-приложение недоступна.');
        return;
      }
      token = data.access_token;
      stage = 'photos.getWallUploadServer через VK Bridge';
      setStatus('Право photos получено. Проверяем доступ к загрузке на стену…');
      const response = await bridge.send('VKWebAppCallAPIMethod', {
        method: 'photos.getWallUploadServer',
        params: { group_id: GROUP_ID, v: '5.199', access_token: token },
      });
      if (response?.error || response?.response?.error) throw response.error || response.response.error;
      if (!response?.response?.upload_url) {
        setStatus('ВК ответил без адреса загрузки. Этот способ пока не подтверждён.');
        return;
      }
      setStatus('Проверка пройдена: ВК выдал адрес загрузки фото на стену сообщества через мини-приложение.\nНичего не загружено и не опубликовано. Следующий этап — загрузка одного постера и проверка его сохранения. Это ещё не подтверждает круглосуточный автопостинг с сервера.');
    } catch (error) {
      setStatus(`Не пройдена проверка: ${stage} (${safeError(error)}).\nНичего не загружено и не опубликовано. Пришлите скрин этого результата.`);
    } finally {
      token = '';
      button.disabled = false;
    }
  });
  upload.addEventListener('click', async () => {
    button.disabled = upload.disabled = true;
    let stage = 'разрешение photos';
    try {
      setStatus('Получаем разрешение на сохранение тестового постера…');
      const auth = await bridge.send('VKWebAppGetAuthToken', { app_id: APP_ID, scope: 'photos' });
      if (!auth.access_token || !String(auth.scope || '').split(/[\s,]+/).includes('photos')) {
        setStatus('ВК не предоставил право photos. Постер не загружен.');
        return;
      }
      token = auth.access_token;
      const api = async (method, values) => {
        const data = await bridge.send('VKWebAppCallAPIMethod', {
          method, params: { ...values, v: '5.199', access_token: token },
        });
        if (data?.error || data?.response?.error) throw data.error || data.response.error;
        return data?.response;
      };
      stage = 'получение адреса загрузки';
      const server = await api('photos.getWallUploadServer', { group_id: GROUP_ID });
      if (!server?.upload_url) throw { error_code: 0 };
      stage = 'передача постера в ВК';
      setStatus('Загружаем постер «Закон и порядок. Специальный корпус»…');
      const response = await fetch('/api/vk/poster-check', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ upload_url: server.upload_url }),
      });
      if (!response.ok) {
        // Our endpoint returns fixed messages only, never VK request parameters.
        setStatus(`Загрузка остановлена: ${await response.text()}.\nПост на стене не создан.`);
        return;
      }
      const receipt = await response.json();
      stage = 'photos.saveWallPhoto';
      const saved = await api('photos.saveWallPhoto', {
        group_id: GROUP_ID, photo: receipt.photo, server: receipt.server, hash: receipt.hash,
      });
      const photo = Array.isArray(saved) ? saved[0] : saved?.items?.[0] || saved?.photos?.[0];
      const ownerId = Number(photo?.owner_id);
      const photoId = Number(photo?.id);
      const summary = `Ответ: ${Array.isArray(saved) ? 'массив, элементов ' + saved.length : typeof saved}; `
        + `владелец: ${Number.isSafeInteger(ownerId) ? ownerId : 'не указан'}; `
        + `фото: ${Number.isSafeInteger(photoId) ? photoId : 'не указано'}.`;
      if (ownerId !== -GROUP_ID || !Number.isSafeInteger(photoId) || photoId <= 0) {
        setStatus('ВК не подтвердил сохранение фото в нашем сообществе.\n' + summary + '\nПост не создан. Пришлите этот результат.');
        return;
      }
      const attachment = `photo${ownerId}_${photoId}`;
      stage = 'проверка сохранённой фотографии';
      const found = await api('photos.getById', { photos: attachment.replace('photo', '') });
      const foundPhotos = Array.isArray(found) ? found : found?.items;
      if (!Array.isArray(foundPhotos) || !foundPhotos.some(p => Number(p.owner_id) === ownerId && Number(p.id) === photoId)) {
        setStatus('ВК вернул идентификатор фото, но повторная проверка его не подтвердила.\n' + summary + '\nПост не создан.');
        return;
      }
      setStatus(`Постер сохранён в сообществе и проверен: ${attachment}\nПост на стене не создан. Пришлите этот результат: теперь можно проверить прикрепление фотографии к записи.`);
    } catch (error) {
      setStatus(`Загрузка остановлена: ${stage} (${safeError(error)}).\nПост на стене не создан. Пришлите скрин результата.`);
    } finally {
      token = '';
      button.disabled = upload.disabled = false;
    }
  });
  verify.addEventListener('click', async () => {
    button.disabled = upload.disabled = verify.disabled = true;
    try {
      setStatus('Проверяем настоящие вложения записи №11…');
      const auth = await bridge.send('VKWebAppGetAuthToken', { app_id: APP_ID, scope: 'photos' });
      if (!auth.access_token) throw { error_code: 5 };
      token = auth.access_token;
      const data = await bridge.send('VKWebAppCallAPIMethod', {
        method: 'wall.getById', params: { posts: '-242059739_11', v: '5.199', access_token: token },
      });
      if (data?.error || data?.response?.error) throw data.error || data.response.error;
      const items = Array.isArray(data?.response) ? data.response : data?.response?.items;
      const post = items?.find(p => Number(p.id) === 11 && Number(p.owner_id) === -GROUP_ID);
      if (!post) {
        setStatus('ВК не вернул запись №11. Проверка картинки пока невозможна. Новый пост не создан.');
        return;
      }
      const photos = (post.attachments || []).filter(a => a.type === 'photo' && a.photo)
        .map(a => ({ owner: Number(a.photo.owner_id), id: Number(a.photo.id) }))
        .filter(p => Number.isSafeInteger(p.owner) && Number.isSafeInteger(p.id) && p.id > 0);
      const exact = photos.some(p => p.owner === 21432243 && p.id === 457248089);
      setStatus(photos.length
        ? `Запись №11 содержит фотографий: ${photos.length}.\n${photos.map(p => 'photo' + p.owner + '_' + p.id).join('\n')}\n`
          + (exact ? 'Идентификатор исходного постера совпал.' : 'Идентификаторы отличаются от исходного постера: нужно сверить изображение визуально.')
          + '\nhttps://vk.ru/wall-242059739_11\nЭто только проверка. Новый пост не создан.'
        : 'На момент проверки ВК вернул запись №11 без вложений типа photo.\nНовый пост не создан. Если картинка видна в ленте, пришлите ссылку на эту запись: она может быть другой публикацией или предпросмотром ссылки.');
    } catch (error) {
      setStatus(`Проверка записи №11 не выполнена (${safeError(error)}).\nОткройте https://vk.ru/wall-242059739_11 и проверьте изображение. Новый пост не создан.`);
    } finally {
      token = '';
      button.disabled = upload.disabled = verify.disabled = false;
    }
  });
  editor.addEventListener('click', async () => {
    editor.disabled = true;
    try {
      setStatus('Подготавливаем сохранённый постер и текст для редактора ВК…');
      const auth = await bridge.send('VKWebAppGetAuthToken', { app_id: APP_ID, scope: 'photos' });
      if (!auth.access_token) throw { error_code: 5 };
      token = auth.access_token;
      const data = await bridge.send('VKWebAppCallAPIMethod', {
        method: 'photos.getById', params: { photos: '21432243_457248089', v: '5.199', access_token: token },
      });
      if (data?.error || data?.response?.error) throw data.error || data.response.error;
      const photos = Array.isArray(data?.response) ? data.response : data?.response?.items;
      const photo = photos?.find(p => Number(p.owner_id) === 21432243 && Number(p.id) === 457248089);
      if (!photo) {
        setStatus('Сохранённый постер недоступен этому аккаунту. Редактор не открыт.');
        return;
      }
      let attachment = 'photo21432243_457248089';
      if (typeof photo.access_key === 'string' && /^[a-zA-Z0-9_-]{1,256}$/.test(photo.access_key)) {
        attachment += '_' + photo.access_key;
      }
      const response = await fetch('/static/vk-post-trial.json');
      if (!response.ok) throw { error_code: 0 };
      const draft = await response.json();
      token = '';
      setStatus('В редакторе проверьте постер и сообщество «КиноЖдун». Подтвердите публикацию только если всё отображается правильно.');
      const result = await bridge.send('VKWebAppShowWallPostBox', {
        owner_id: -GROUP_ID, message: draft.text, attachments: attachment, signed: false,
      });
      const id = Number(result?.post_id);
      setStatus(Number.isSafeInteger(id) && id > 0
        ? `ВК подтвердил публикацию из редактора, ID ${id}. Проверьте запись в сообществе и пришлите результат.`
        : 'Редактор закрыт. Подтверждения публикации нет.');
    } catch (error) {
      setStatus(`Редактор ВК не подтвердил публикацию (${safeError(error)}).\nАвтопубликация остаётся выключенной.`);
    } finally {
      token = '';
      editor.disabled = false;
    }
  });
  window.addEventListener('pagehide', () => { token = ''; });
  init();
})();
