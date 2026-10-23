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

  // pages: each sidebar item shows only its own sections; the address (#/reels) keeps the page on
  // reload and makes the browser's back button work
  const PAGES = {
    top: ['top', 'kpis'], goals: ['goals'], plan: ['plan'], reels: ['reels'], works: ['works'],
    growth: ['growth'], besttime: ['besttime'], experiments: ['experiments'], insights: ['insights', 'ideas'],
    competitors: ['competitors'], audience: ['audience'], checklist: ['checklist'],
    assistant: ['assistant'], reel: ['reel'],  // reel takes the reel's shortcode: #/reel/DeuAledNcym
  };
  const links = new Map([...document.querySelectorAll('.sidebar .nav-item[data-sec]')].map((a) => [a.dataset.sec, a]));
  const sections = Object.values(PAGES).flat().map((id) => document.getElementById(id)).filter(Boolean);
  const pageTitle = document.getElementById('sj-page-title');
  let baseTitle = document.title;
  let pageLabel = '';
  const setTitle = () => { document.title = pageLabel ? pageLabel + ' · ' + baseTitle : baseTitle; };
  const show = (id, param) => {
    if (!PAGES[id]) id = 'top';
    const want = new Set(PAGES[id]);
    sections.forEach((el) => {
      el.hidden = !want.has(el.id);
      // a one-section page already has its title in the page header; pages with two keep each heading
      const h = el.querySelector(':scope > .sj-h2');
      if (h) h.hidden = PAGES[id].length === 1;
    });
    links.forEach((a, sec) => {
      const on = sec === id;
      a.classList.toggle('is-active', on);
      if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    const label = links.get(id) && links.get(id).querySelector('.sidebar-label');
    // pages without a sidebar item (a single reel) name themselves with data-title
    const own = document.getElementById(PAGES[id][0]);
    pageLabel = label ? label.textContent : (own && own.dataset.title) || '';
    if (pageTitle) pageTitle.textContent = pageLabel;
    setTitle();
    window.scrollTo(0, 0);
    const dash = document.getElementById('dash-root');
    if (dash) { dash.classList.remove('sj-page-in'); void dash.offsetWidth; dash.classList.add('sj-page-in'); }
    window.dispatchEvent(new Event('resize'));  // charts on a hidden page were drawn without a width
    window.dispatchEvent(new CustomEvent('sj:page', { detail: { page: id, param: param || '' } }));
  };
  const route = () => {
    const m = location.hash.match(/^#\/?([a-z]+)(?:\/([A-Za-z0-9_-]+))?$/);
    show(m ? m[1] : 'top', m ? m[2] : '');
  };
  window.addEventListener('hashchange', route);
  route();

  // Persian digits everywhere in the dashboard, including what charts and tables draw later:
  // 14,317 → ۱۴٬۳۱۷, 47.8% → ۴۷٫۸٪. Code, inputs and links' addresses keep Latin digits; CSV
  // downloads come from the data, not the page, so they keep plain numbers.
  const FA = '۰۱۲۳۴۵۶۷۸۹';
  const SKIP = 'code, pre, input, textarea, script, style, [data-latin]';
  const toFa = (t) => t
    .replace(/(\d),(?=\d{3}\b)/g, '$1٬')
    .replace(/(\d)\.(\d)/g, '$1٫$2')
    .replace(/(\d)\s?%/g, '$1٪')
    .replace(/\d/g, (d) => FA[d]);
  const convert = (node) => {
    if (node.nodeType === 3) {
      const p = node.parentElement;
      if (!p || p.closest(SKIP) || !/\d/.test(node.data)) return;
      const t = toFa(node.data);
      if (t !== node.data) node.data = t;  // unchanged text isn't touched, so the observer doesn't loop
    } else if (node.nodeType === 1 && !node.matches(SKIP)) {
      const walk = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
      for (let n = walk.nextNode(); n; n = walk.nextNode()) convert(n);
    }
  };
  const dashRoot = document.getElementById('dash-root');
  if (dashRoot) {
    convert(dashRoot);
    new MutationObserver((muts) => muts.forEach((m) => {
      if (m.type === 'characterData') convert(m.target);
      else m.addedNodes.forEach(convert);
    })).observe(dashRoot, { childList: true, characterData: true, subtree: true });
  }

  // signed-in user (panel only)
  const greet = () => { const h = new Date().getHours(); return h < 5 ? 'شب بخیر' : h < 12 ? 'صبح بخیر' : h < 17 ? 'روز بخیر' : 'عصر بخیر'; };
  fetch('/api/me', { credentials: 'same-origin' }).then((r) => (r.ok ? r.json() : null)).then((me) => {
    if (!me) return;
    const page = (me.prefs && me.prefs.page_name) || me.username;
    baseTitle = 'داشبورد ' + page;
    setTitle();
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
