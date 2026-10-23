/* The dashboard shell (Sepehr design): theme, sidebar, profile menu, the section the reader is on,
   and — when served by the panel — the signed-in user. Works without the panel too: the panel-only
   links stay hidden when /api/me isn't there. */
(function () {
  const root = document.documentElement;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } },
  };

  // theme (the head script already applied the saved one before first paint)
  const themeBtn = document.querySelector('[data-theme-toggle]');
  const syncThemeLabel = () => {
    if (themeBtn) themeBtn.setAttribute('aria-label', root.getAttribute('data-theme') === 'light' ? 'پوستهٔ تیره' : 'پوستهٔ روشن');
  };
  syncThemeLabel();
  if (themeBtn) themeBtn.addEventListener('click', () => {
    const next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    root.setAttribute('data-theme', next);
    store.set('sj-theme', next);
    syncThemeLabel();
    window.dispatchEvent(new Event('resize'));  // charts redraw with the new colours
  });

  // sidebar: collapse on wide screens, slide in on narrow ones
  const collapseBtn = document.querySelector('[data-collapse-sidebar]');
  const setCollapsed = (on) => {
    root.classList.toggle('sidebar-collapsed', on);
    store.set('sj-sidebar', on ? '1' : '0');
    if (collapseBtn) collapseBtn.setAttribute('aria-expanded', String(!on));
  };
  if (collapseBtn) collapseBtn.addEventListener('click', () => {
    setCollapsed(!root.classList.contains('sidebar-collapsed'));
    setTimeout(() => window.dispatchEvent(new Event('resize')), 260);  // charts follow the new width
  });
  const openBtn = document.querySelector('[data-open-sidebar]');
  const closeMobile = () => { root.classList.remove('sidebar-open'); if (openBtn) openBtn.setAttribute('aria-expanded', 'false'); };
  if (openBtn) openBtn.addEventListener('click', () => { root.classList.add('sidebar-open'); openBtn.setAttribute('aria-expanded', 'true'); });
  document.querySelectorAll('[data-overlay], [data-close-sidebar]').forEach((el) => el.addEventListener('click', closeMobile));
  document.querySelectorAll('.sidebar .nav-item[href^="#"]').forEach((a) => a.addEventListener('click', closeMobile));

  // profile menu
  const closeMenus = () => {
    document.querySelectorAll('[data-dropdown].is-open').forEach((m) => m.classList.remove('is-open'));
    document.querySelectorAll('[data-dropdown-trigger]').forEach((b) => b.setAttribute('aria-expanded', 'false'));
  };
  document.querySelectorAll('[data-dropdown-trigger]').forEach((btn) => btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const menu = document.getElementById(btn.getAttribute('data-dropdown-trigger'));
    const open = !menu.classList.contains('is-open');
    closeMenus();
    menu.classList.toggle('is-open', open);
    btn.setAttribute('aria-expanded', String(open));
  }));
  document.addEventListener('click', closeMenus);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeMenus(); closeMobile(); } });

  // highlight the section in view
  const links = new Map([...document.querySelectorAll('.sidebar .nav-item[data-sec]')].map((a) => [a.dataset.sec, a]));
  const setActive = (id) => links.forEach((a, sec) => {
    const on = sec === id;
    a.classList.toggle('is-active', on);
    if (on) a.setAttribute('aria-current', 'location'); else a.removeAttribute('aria-current');
  });
  if ('IntersectionObserver' in window) {
    const seen = new Map();
    const io = new IntersectionObserver((entries) => {
      entries.forEach((en) => seen.set(en.target.id, en.isIntersecting ? en.intersectionRatio : 0));
      // the topmost section that's visible
      const visible = [...links.keys()].filter((id) => (seen.get(id) || 0) > 0);
      if (visible.length) setActive(visible[0]);
    }, { rootMargin: '-72px 0px -55% 0px', threshold: [0, 0.01] });
    links.forEach((_, id) => { const el = document.getElementById(id); if (el) io.observe(el); });
  }

  // signed-in user (panel only)
  const greet = () => { const h = new Date().getHours(); return h < 5 ? 'شب بخیر' : h < 12 ? 'صبح بخیر' : h < 17 ? 'روز بخیر' : 'عصر بخیر'; };
  fetch('/api/me', { credentials: 'same-origin' }).then((r) => (r.ok ? r.json() : null)).then((me) => {
    if (!me) return;
    const page = (me.prefs && me.prefs.page_name) || me.username;
    document.title = 'داشبورد ' + page;
    document.getElementById('sj-brand').textContent = page;
    document.getElementById('sj-topbar-title').textContent = 'داشبورد ' + page;
    document.getElementById('sj-greeting').textContent = greet() + '، ' + me.username;
    document.querySelectorAll('[data-user-name]').forEach((el) => { el.textContent = me.username; });
    document.querySelectorAll('[data-user-initials]').forEach((el) => { el.textContent = me.username.slice(0, 2).toUpperCase(); });
    document.querySelectorAll('[data-user-role]').forEach((el) => { el.textContent = me.is_admin ? 'ادمین پنل' : 'کاربر'; });
    document.querySelectorAll('[data-panel-only]').forEach((el) => { el.hidden = false; });
    if (me.is_admin) document.querySelectorAll('[data-admin-only]').forEach((el) => { el.hidden = false; });
  }).catch(() => { /* served without the panel */ });
})();
