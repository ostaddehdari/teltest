(() => {
  const navItems = [...document.querySelectorAll('[data-panel]')];
  const panels = [...document.querySelectorAll('[data-panel-content]')];
  const title = document.getElementById('pageTitle');
  const sidebar = document.getElementById('sidebar');
  const menuButton = document.getElementById('menuButton');

  const titles = {
    dashboard: 'داشبورد',
    jobs: 'جاب‌ها',
    posts: 'پست‌های استخراجی',
    accounts: 'اکانت‌های تلگرام',
    channels: 'کانال‌ها',
    logs: 'لاگ‌ها',
    settings: 'تنظیمات',
  };

  function openPanel(name) {
    navItems.forEach((item) => item.classList.toggle('active', item.dataset.panel === name));
    panels.forEach((panel) => panel.classList.toggle('active', panel.dataset.panelContent === name));
    if (title) title.textContent = titles[name] || 'TelTest';
    if (window.innerWidth <= 900 && sidebar) sidebar.classList.remove('open');
    history.replaceState(null, '', `#${name}`);
  }

  navItems.forEach((item) => item.addEventListener('click', () => openPanel(item.dataset.panel)));
  document.querySelectorAll('[data-open-panel]').forEach((item) => {
    item.addEventListener('click', () => openPanel(item.dataset.openPanel));
  });

  if (menuButton && sidebar) {
    menuButton.addEventListener('click', () => sidebar.classList.toggle('open'));
  }

  const initial = location.hash.replace('#', '');
  if (titles[initial]) openPanel(initial);
})();
