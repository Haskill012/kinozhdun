// Images stay optional: articles and navigation always work without JavaScript.
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
