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
    assistant: ['assistant'], studio: ['studio'], screenshot: ['screenshot'], board: ['board'], publish: ['publish'], comments: ['comments'], reel: ['reel'],  // reel takes the reel's shortcode: #/reel/DeuAledNcym
  };
  const NO_RANGE = new Set(['assistant', 'studio', 'screenshot', 'board', 'publish', 'comments', 'checklist', 'experiments', 'reel']);
  const links = new Map([...document.querySelectorAll('.sidebar .nav-item[data-sec]')].map((a) => [a.dataset.sec, a]));
  const sections = Object.values(PAGES).flat().map((id) => document.getElementById(id)).filter(Boolean);
  // A page's sections leave the document when another page opens (not just hidden), and come back at
  // the same place: each keeps a comment where it belongs. The page's scripts still draw into them while
  // they're out (their data keeps arriving), so lookups by id or selector also look in the parked sections.
  const slot = new Map(sections.map((el) => { const c = document.createComment('page:' + el.id); el.before(c); return [el, c]; }));
  const parked = () => sections.filter((el) => !el.isConnected);
  const byId = document.getElementById.bind(document), qs = document.querySelector.bind(document), qsa = document.querySelectorAll.bind(document);
  document.getElementById = (id) => {
    const hit = byId(id);
    if (hit) return hit;
    for (const el of parked()) { if (el.id === id) return el; const f = el.querySelector('#' + CSS.escape(id)); if (f) return f; }
    return null;
  };
  document.querySelector = (sel) => {
    const hit = qs(sel);
    if (hit) return hit;
    for (const el of parked()) { try { if (el.matches(sel)) return el; const f = el.querySelector(sel); if (f) return f; } catch (e) { return null; } }
    return null;
  };
  document.querySelectorAll = (sel) => {
    const out = [...qsa(sel)];
    for (const el of parked()) { try { if (el.matches(sel)) out.push(el); out.push(...el.querySelectorAll(sel)); } catch (e) { /* bad selector: same as before */ } }
    return out;
  };
  const pageTitle = document.getElementById('sj-page-title');
  let baseTitle = document.title;
  let pageLabel = '';
  const setTitle = () => { document.title = pageLabel ? pageLabel + ' · ' + baseTitle : baseTitle; };
  const show = (id, param) => {
    if (!PAGES[id]) id = 'top';
    const want = new Set(PAGES[id]);
    sections.forEach((el) => {
      const on = want.has(el.id);
      if (on && !el.isConnected) slot.get(el).after(el);
      if (!on && el.isConnected) el.remove();
      el.hidden = !on;
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
    // the 7/30/all control only means something on pages drawn from a date range
    const range = document.getElementById('sj-range');
    if (range) range.hidden = NO_RANGE.has(id);
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
    const pageName = (me.prefs && me.prefs.page_name) || '';  // a chosen page name only — never the phone/username
    const title = 'داشبورد' + (pageName ? ' · ' + pageName : '');
    baseTitle = title;
    setTitle();
    document.getElementById('sj-brand').textContent = pageName || 'داشبورد';
    document.getElementById('sj-topbar-title').textContent = title;
    document.getElementById('sj-greeting').textContent = greet() + '، ' + me.username;
    document.querySelectorAll('[data-user-name]').forEach((el) => { el.textContent = me.username; });
    document.querySelectorAll('[data-user-initials]').forEach((el) => { el.textContent = me.username.slice(0, 2).toUpperCase(); });
    const ROLE = { owner: 'صاحب پیج', editor: 'ویرایشگر', viewer: 'فقط دیدن' };
    document.querySelectorAll('[data-user-role]').forEach((el) => { el.textContent = (me.page && !me.page.own ? ROLE[me.role] + ' · ' : '') + (me.is_admin ? 'ادمین پنل' : 'کاربر'); });
    root.classList.add('sj-panel');  // panel-only buttons drawn later (idea cards) show through CSS
    root.classList.toggle('sj-ro', me.role === 'viewer');  // a viewer's page hides the buttons that change things
    // pages: the ones this person can open, and a new one
    const list = document.getElementById('sj-page-list');
    if (list && me.pages) {
      list.replaceChildren(...me.pages.map((p) => {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'dropdown-item text-sm sj-page-item' + (p.id === me.page.id ? ' is-current' : '');
        b.textContent = p.name;
        if (p.role !== 'owner') { const r = document.createElement('small'); r.textContent = ROLE[p.role]; b.append(r); }
        b.addEventListener('click', async () => {
          if (p.id === me.page.id) return;
          const r = await fetch('/api/me/switch', { method: 'POST', credentials: 'same-origin', headers: { 'X-Requested-With': 'sajadai', 'Content-Type': 'application/json' }, body: JSON.stringify({ page: p.id }) });
          if (r.ok) location.reload();
        });
        return b;
      }));
      document.getElementById('sj-new-page').addEventListener('click', async () => {
        const name = prompt('اسم پیج تازه (مثلاً اسم پیج اینستاگرامش):');
        if (!name || !name.trim()) return;
        const r = await fetch('/api/pages', { method: 'POST', credentials: 'same-origin', headers: { 'X-Requested-With': 'sajadai', 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.trim() }) });
        const d = await r.json().catch(() => ({}));
        if (r.ok) location.href = '/settings';  // a new page starts with connecting its sources
        else alert(d.detail || 'ساخته نشد');
      });
    }
    // installable app: only the panel has a manifest and a service worker to offer
    const ml = document.createElement('link'); ml.rel = 'manifest'; ml.href = '/manifest.webmanifest'; document.head.append(ml);
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => { /* not over https */ });
    document.querySelectorAll('[data-panel-only]').forEach((el) => { el.hidden = false; });
    if (me.is_admin) document.querySelectorAll('[data-admin-only]').forEach((el) => { el.hidden = false; });
  }).catch(() => { /* served without the panel */ });
})();
