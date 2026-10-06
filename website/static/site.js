// Images stay optional: articles and navigation always work without JavaScript.
const siteSearch = document.querySelector('.site-search');
if (siteSearch) {
  const input = siteSearch.querySelector('input');
  const dropdown = siteSearch.querySelector('.site-search-dropdown');
  const results = siteSearch.querySelector('[role="listbox"]');
  const status = siteSearch.querySelector('.site-search-status');
  const all = siteSearch.querySelector('.site-search-all');
  const clear = siteSearch.querySelector('.site-search-clear');
  let timer, controller, revision = 0, active = -1;
  const close = () => {
    dropdown.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    active = -1;
  };
  const show = () => {
    dropdown.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  };
  const select = index => {
    const options = [...results.children];
    active = index;
    options.forEach((option, i) => option.setAttribute('aria-selected', String(i === active)));
    if (options[active]) {
      input.setAttribute('aria-activedescendant', options[active].id);
      options[active].scrollIntoView({ block: 'nearest' });
    }
  };
  const search = async () => {
    clearTimeout(timer);
    if (controller) controller.abort();
    const request = ++revision;
    const query = input.value.trim();
    clear.hidden = !query;
    results.replaceChildren();
    input.removeAttribute('aria-activedescendant');
    active = -1;
    all.href = '/catalog?q=' + encodeURIComponent(query);
    all.hidden = query.length < 2;
    if (query.length < 2) {
      status.textContent = 'Введите хотя бы два символа';
      if (query) show(); else close();
      return;
    }
    show();
    status.textContent = 'Ищем…';
    timer = setTimeout(async () => {
      controller = new AbortController();
      try {
        const response = await fetch('/api/search?q=' + encodeURIComponent(query), { signal: controller.signal });
        if (!response.ok) throw new Error('Search unavailable');
        const data = await response.json();
        if (request !== revision) return;
        status.textContent = data.results.length ? 'Найденные проекты' : 'Ничего не найдено. Попробуйте другое название.';
        data.results.forEach((item, index) => {
          const link = document.createElement('a');
          link.className = 'site-search-result';
          link.id = 'site-search-option-' + index;
          link.href = item.url;
          link.setAttribute('role', 'option');
          link.setAttribute('aria-selected', 'false');
          link.tabIndex = -1;
          const poster = document.createElement('span');
          poster.className = 'site-search-poster';
          poster.textContent = 'КЖ';
          if (item.poster && item.poster.startsWith('https://image.tmdb.org/')) {
            const img = document.createElement('img');
            img.src = item.poster;
            img.alt = '';
            img.loading = 'lazy';
            img.addEventListener('error', () => img.remove(), { once: true });
            poster.append(img);
          }
          const copy = document.createElement('span');
          const title = document.createElement('strong');
          title.textContent = item.title;
          const meta = document.createElement('small');
          const parts = [item.media_type === 'tv' ? 'Сериал' : 'Фильм'];
          if (item.year) parts.push(item.year);
          if (Number(item.rating) > 0) parts.push('★ ' + Number(item.rating).toFixed(1) + ' TMDB');
          meta.textContent = parts.join(' · ');
          copy.append(title, meta);
          link.append(poster, copy);
          results.append(link);
        });
      } catch (error) {
        if (error.name !== 'AbortError' && request === revision) {
          status.textContent = 'Не удалось загрузить подсказки. Откройте все результаты.';
        }
      }
    }, 180);
  };
  input.addEventListener('input', search);
  input.addEventListener('focus', () => { if (input.value.trim()) search(); });
  input.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      ++revision;
      clearTimeout(timer);
      if (controller) controller.abort();
      close();
      return;
    }
    const count = results.children.length;
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && count) {
      event.preventDefault();
      show();
      select(event.key === 'ArrowDown' ? (active + 1) % count : (active <= 0 ? count - 1 : active - 1));
    } else if (event.key === 'Enter' && active >= 0 && !dropdown.hidden) {
      event.preventDefault();
      results.children[active].click();
    }
  });
  clear.addEventListener('click', () => { input.value = ''; search(); input.focus(); });
  document.addEventListener('pointerdown', event => { if (!siteSearch.contains(event.target)) close(); });
  siteSearch.addEventListener('focusout', () => setTimeout(() => {
    if (!siteSearch.contains(document.activeElement)) close();
  }, 0));
}

document.querySelectorAll('img').forEach(img => {
  img.addEventListener('error', () => {
    const fallback = document.createElement('div');
    fallback.className = img.className + ' art-placeholder';
    fallback.innerHTML = '<span>КЖ</span><small>КИНО — ЭТО ОЖИДАНИЕ</small>';
    img.replaceWith(fallback);
  }, { once: true });
});

// Keep search immediate; optional filters use a native accordion on phones.
const filterPanel = document.querySelector('.catalog-filter-more');
if (filterPanel) {
  const desktopFilters = window.matchMedia('(min-width: 521px)');
  const syncFilterPanel = () => { filterPanel.open = desktopFilters.matches; };
  syncFilterPanel();
  desktopFilters.addEventListener('change', syncFilterPanel);
}

// Record intent to open Telegram; these events do not imply a bot registration.
const metrikaId = document.body.dataset.metrikaId;
if (/^\d+$/.test(metrikaId || '')) {
  const botUrl = new URL(document.body.dataset.botUrl);
  const channelUrl = new URL(document.body.dataset.channelUrl);
  const sameDestination = (url, target) => url.origin === target.origin &&
    url.pathname.replace(/\/$/, '').toLowerCase() === target.pathname.replace(/\/$/, '').toLowerCase();
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || typeof window.ym !== 'function') return;
    const url = new URL(link.href);
    if (sameDestination(url, botUrl)) {
      window.ym(Number(metrikaId), 'reachGoal', 'bot_click');
      if (/^c_(movie|tv)_\d+$/.test(url.searchParams.get('start') || '')) {
        window.ym(Number(metrikaId), 'reachGoal', 'watchlist_click');
      }
    } else if (url.origin === channelUrl.origin && (sameDestination(url, channelUrl) ||
      url.pathname.toLowerCase().startsWith(channelUrl.pathname.replace(/\/$/, '').toLowerCase() + '/'))) {
      window.ym(Number(metrikaId), 'reachGoal', 'channel_click');
    }
  });
}
