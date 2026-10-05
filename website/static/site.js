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
