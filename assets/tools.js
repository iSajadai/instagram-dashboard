/* Panel tools on the dashboard: the assistant chat, the hook/caption writer, and a page for each reel
   (#/reel/<shortcode>) with an AI critique. They need the panel (/api/me/...); served as a static
   page their sidebar items stay hidden. Loaded before shell.js so it hears the first page event. */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // a little formatting for model text: paragraphs, **bold**, "- " lists; everything else stays plain text
  const fmt = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').split(/\n{2,}/).map((p) => {
    const lines = p.split('\n');
    return lines.every((l) => /^\s*[-•*]\s+/.test(l))
      ? '<ul>' + lines.map((l) => '<li>' + l.replace(/^\s*[-•*]\s+/, '') + '</li>').join('') + '</ul>'
      : '<p>' + lines.join('<br>') + '</p>';
  }).join('');
  async function api(method, path, body) {
    const r = await fetch(path, {
      method, credentials: 'same-origin',
      headers: { 'X-Requested-With': 'sajadai', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await r.json(); } catch (e) { /* empty */ }
    if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'خطا (' + r.status + ')');
    return data;
  }
  const busy = (btn, on, label) => { if (!btn) return; btn.disabled = on; if (label) btn.textContent = on ? 'صبر کن…' : label; };
  const store = {
    get(k) { try { return JSON.parse(sessionStorage.getItem(k) || 'null'); } catch (e) { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private window */ } },
  };

  // ---------- chat ----------
  let chat = store.get('sj-chat') || [];
  const log = $('chat-log');
  const drawChat = (pending) => {
    if (!log) return;
    log.innerHTML = chat.map((m) => `<div class="sj-msg ${m.role === 'user' ? 'me' : 'ai'}">${m.role === 'user' ? esc(m.content) : fmt(m.content)}</div>`).join('')
      + (pending ? '<div class="sj-msg ai sj-typing"><span></span><span></span><span></span></div>' : '');
    if (!chat.length && !pending) log.innerHTML = '<p class="sj-note">هنوز سؤالی نپرسیدی.</p>';
    log.scrollTop = log.scrollHeight;
  };
  async function ask(text) {
    text = text.trim();
    if (!text) return;
    chat.push({ role: 'user', content: text });
    drawChat(true);
    busy($('chat-send'), true, 'بپرس');
    try {
      const r = await api('POST', '/api/me/chat', { messages: chat.slice(-12) });
      chat.push({ role: 'assistant', content: r.answer });
    } catch (e) {
      chat.push({ role: 'assistant', content: '⚠️ ' + e.message });
    }
    store.set('sj-chat', chat.slice(-30));
    busy($('chat-send'), false, 'بپرس');
    drawChat(false);
  }
  if ($('chat-form')) {
    drawChat(false);
    $('chat-form').addEventListener('submit', (e) => { e.preventDefault(); const t = $('chat-input').value; $('chat-input').value = ''; ask(t); });
    $('chat-input').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('chat-form').requestSubmit(); } });
    $('chat-suggest').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) ask(b.textContent); });
    $('chat-clear').addEventListener('click', () => { chat = []; store.set('sj-chat', chat); drawChat(false); });
  }

  // ---------- hook / caption writer ----------
  const dialog = $('writer-dialog');
  const copyBtn = (text) => `<button type="button" class="sj-btn sj-copy" data-copy="${esc(text)}">کپی</button>`;
  async function write(payload, btn, label) {
    busy(btn, true, label);
    try {
      const r = await api('POST', '/api/me/write-caption', payload);
      const tags = (r.hashtags || []).map((h) => '#' + String(h).replace(/^#/, '').replace(/\s+/g, '_')).join(' ');
      $('writer-out').innerHTML =
        '<h4>سه هوک</h4>' + (r.hooks || []).map((h) => `<div class="sj-out-row"><p>${esc(h)}</p>${copyBtn(h)}</div>`).join('') +
        `<h4>کپشن</h4><div class="sj-out-row"><p>${esc(r.caption).replace(/\n/g, '<br>')}</p>${copyBtn(r.caption)}</div>` +
        `<h4>هشتگ</h4><div class="sj-out-row"><p dir="ltr">${esc(tags)}</p>${copyBtn(tags)}</div>` +
        `<h4>جملهٔ پایانی</h4><div class="sj-out-row"><p>${esc(r.cta)}</p>${copyBtn(r.cta)}</div>`;
    } catch (e) {
      $('writer-out').innerHTML = `<p class="sj-error">${esc(e.message)}</p>`;
    }
    busy(btn, false, label);
    if (dialog && !dialog.open) dialog.showModal();
  }
  if (dialog) {
    dialog.addEventListener('click', async (e) => {
      if (e.target === dialog || e.target.closest('[data-close]')) dialog.close();
      const c = e.target.closest('.sj-copy');
      if (c) { try { await navigator.clipboard.writeText(c.dataset.copy); c.textContent = 'کپی شد ✓'; setTimeout(() => { c.textContent = 'کپی'; }, 1500); } catch (err) { /* no clipboard */ } }
    });
  }
  if ($('writer-form')) {
    $('writer-form').addEventListener('submit', (e) => {
      e.preventDefault();
      const t = $('writer-topic').value.trim();
      if (t) write({ text: t }, e.submitter, 'بنویس');
    });
  }
  // a "write the caption" button on every idea card (cards are redrawn when data changes)
  const ideas = $('ideas-list');
  const addWriterButtons = () => ideas.querySelectorAll('article.sj-idea').forEach((card) => {
    if (card.querySelector('.sj-write')) return;
    const f = (k) => (card.querySelector(`[data-field="${k}"]`) || {}).textContent || '';
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'sj-btn sj-write'; b.textContent = 'نوشتن کپشن';
    b.addEventListener('click', () => write({ title: f('title'), hook: f('hook'), beats: f('beats') }, b, 'نوشتن کپشن'));
    const toBoard = document.createElement('button');
    toBoard.type = 'button'; toBoard.className = 'sj-btn sj-write'; toBoard.textContent = 'به بُرد تولید';
    toBoard.addEventListener('click', async () => {
      if (!window.sjBoard) return;
      busy(toBoard, true, 'به بُرد تولید');
      try { await window.sjBoard.add({ title: f('title'), hook: f('hook'), notes: f('beats') }); toBoard.textContent = 'اضافه شد ✓'; }
      catch (e) { toBoard.textContent = 'اضافه نشد'; }
      toBoard.disabled = false;
      setTimeout(() => { toBoard.textContent = 'به بُرد تولید'; }, 2500);
    });
    const row = document.createElement('div'); row.className = 'sj-row-btns'; row.append(b, toBoard);
    card.append(row);
  });
  if (ideas) new MutationObserver(addWriterButtons).observe(ideas, { childList: true });

  // ---------- a page for each reel ----------
  const code = (url) => (String(url).match(/\/(?:reels?|p|tv)\/([A-Za-z0-9_-]+)/) || [])[1] || '';
  const reelsTable = document.querySelector('#reels-table tbody');
  if (reelsTable) {
    reelsTable.addEventListener('click', (e) => {
      if (e.target.closest('a')) return;
      const tr = e.target.closest('tr[data-key]');
      if (tr && code(tr.dataset.key)) location.hash = '#/reel/' + code(tr.dataset.key);
    });
  }
  const tile = (label, value, note) => `<div class="sj-tile sj-mini"><div class="sj-label">${esc(label)}</div><div class="sj-num">${esc(value ?? '—')}</div>${note ? `<div class="sj-def">${esc(note)}</div>` : ''}</div>`;
  const CRIT = [['verdict', 'جمع‌بندی'], ['hook', 'هوک'], ['caption', 'کپشن'], ['cover', 'کاور'], ['what_worked', 'چی جواب داد'], ['what_to_change', 'چی رو عوض کنی'], ['next_reel', 'ریل بعدی']];
  const drawCritique = (c) => {
    const box = $('reel-critique');
    if (!box) return;
    box.innerHTML = c ? CRIT.map(([k, l]) => c[k] ? `<div class="sj-crit"><h4>${l}</h4>${fmt(c[k])}</div>` : '').join('')
      : '<p class="sj-note">هنوز نقدی برای این ریل نوشته نشده.</p>';
  };
  function curve(el, pts) {
    if (!el || !window.d3) return;
    el.replaceChildren();
    if (pts.length < 2) { el.innerHTML = '<div class="sj-fail">هنوز عکس کافی از عددها جمع نشده</div>'; return; }
    const W = el.clientWidth || 600, H = 200, m = { t: 14, r: 14, b: 26, l: 46 };
    const all = [{ hours: 0, views: 0 }].concat(pts);
    const x = d3.scaleLinear([0, d3.max(all, (p) => p.hours) || 1], [m.l, W - m.r]);
    const y = d3.scaleLinear([0, (d3.max(all, (p) => p.views) || 1) * 1.1], [H - m.b, m.t]);
    const svg = d3.select(el).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`);
    y.ticks(4).forEach((t) => {
      svg.append('line').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y(t)).attr('y2', y(t)).attr('stroke', 'var(--cds-chart-grid)');
      svg.append('text').attr('x', m.l - 6).attr('y', y(t) + 4).attr('text-anchor', 'end').attr('font-size', 11).attr('fill', 'var(--color-fg-muted)').text(d3.format(',')(t));
    });
    x.ticks(5).forEach((h) => svg.append('text').attr('x', x(h)).attr('y', H - 6).attr('text-anchor', 'middle').attr('font-size', 11).attr('fill', 'var(--color-fg-muted)').attr('direction', 'rtl').text(h + 'س'));
    svg.append('path').datum(all).attr('fill', 'none').attr('stroke', 'var(--series-1)').attr('stroke-width', 2.5).attr('d', d3.line((p) => x(p.hours), (p) => y(p.views)));
    svg.append('g').selectAll('circle').data(pts).join('circle').attr('cx', (p) => x(p.hours)).attr('cy', (p) => y(p.views)).attr('r', 3.5).attr('fill', 'var(--series-1)');
  }
  async function showReel(c) {
    const body = $('reel-body');
    if (!body) return;
    body.innerHTML = '<p class="sj-note">در حال بارگذاری…</p>';
    let r;
    try { r = await api('GET', '/api/me/reel?reel=' + encodeURIComponent(c)); } catch (e) { body.innerHTML = `<p class="sj-error">${esc(e.message)}</p>`; return; }
    const first = (r.caption || '').split('\n')[0];
    const date = r.published ? new Intl.DateTimeFormat('fa-IR-u-ca-persian-nu-latn', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(r.published)) : '';
    const pct = (v) => (v == null ? '—' : v + '%');
    body.innerHTML = `
      <div class="sj-card sj-reel-head">
        <div><p class="sj-small">${esc(date)}</p><h3>${esc(first || 'ریل')}</h3>
          <p class="sj-note">${esc((r.caption || '').split('\n').slice(1).join(' ').slice(0, 400))}</p>
          <label class="sj-small sj-topic-pick">موضوع: <select id="reel-topic">
            ${(r.topics || []).concat([{ id: 'other', label: 'سایر' }]).map((t) => `<option value="${esc(t.id)}">${esc(t.label)}</option>`).join('')}
          </select> <span id="reel-topic-msg">${r.topic_manual ? 'دستی' : 'از روی کپشن'}</span></label></div>
        <a class="sj-btn" href="${/^https:\/\/(www\.)?instagram\.com\//.test(r.url) ? esc(r.url) : '#'}" target="_blank" rel="noopener">باز کردن در اینستاگرام</a>
      </div>
      <div class="sj-tiles">
        ${tile('بازدید', r.views == null ? '—' : d3.format(',')(r.views), r.page_median_views ? 'میانهٔ پیج: ' + d3.format(',')(Math.round(r.page_median_views)) : '')}
        ${tile('چند برابر میانه', r.multiple_of_median == null ? '—' : r.multiple_of_median + '×', 'بالای ۲ یعنی یه چیزی جواب داده')}
        ${tile('ماندن بعد از ۳ ثانیه', pct(r.view_rate_3s_pct), 'قدرت هوک')}
        ${tile('میانگین تماشا', r.avg_watch_s == null ? '—' : Math.round(r.avg_watch_s * 10) / 10 + ' ث', '')}
        ${tile('نرخ ذخیره', pct(r.save_rate_pct), '')}
        ${tile('فالو از این ریل', r.follows == null ? '—' : r.follows, '')}
      </div>
      <div class="sj-card"><h3>منحنی بازدید بعد از انتشار</h3><div class="sj-chart" id="reel-curve"></div></div>
      <div class="sj-card">
        <div class="sj-tools"><h3>نقد هوش مصنوعی</h3><button class="sj-btn sj-btn-primary" type="button" id="reel-crit-btn">${r.critique ? 'نقد تازه' : 'نقد با هوش مصنوعی'}</button></div>
        <div id="reel-critique"></div>
      </div>`;
    curve($('reel-curve'), r.view_curve || []);
    drawCritique(r.critique);
    const pick = $('reel-topic');
    pick.value = r.topic || 'other';
    pick.addEventListener('change', async () => {
      pick.disabled = true;
      try { await api('POST', '/api/me/reel-topic', { reel: r.url, topic: pick.value }); $('reel-topic-msg').textContent = 'دستی · ذخیره شد ✓'; }
      catch (err) { $('reel-topic-msg').textContent = err.message; }
      pick.disabled = false;
    });
    $('reel-crit-btn').addEventListener('click', async (e) => {
      const b = e.currentTarget, label = b.textContent;
      busy(b, true, label);
      $('reel-critique').innerHTML = '<div class="sj-msg ai sj-typing"><span></span><span></span><span></span></div>';
      try { drawCritique(await api('POST', '/api/me/reel-critique', { reel: c, fresh: !!r.critique })); b.textContent = 'نقد تازه'; }
      catch (err) { $('reel-critique').innerHTML = `<p class="sj-error">${esc(err.message)}</p>`; }
      b.disabled = false;
    });
    document.title = (first.slice(0, 40) || 'ریل') + ' · ' + document.title.split(' · ').slice(-1)[0];
  }
  // ---------- first steps for a new page (checked by the server against what's really set up) ----------
  const onboard = $('onboard');
  async function drawOnboarding() {
    let me;
    try { me = await api('GET', '/api/me'); } catch (e) { return; }
    const o = me.onboarding;
    if (!o || o.hidden || o.done || me.role !== 'owner') { onboard.hidden = true; return; }
    const req = o.steps.filter((s) => !s.optional), done = req.filter((s) => s.done).length;
    onboard.innerHTML = `
      <div class="sj-onboard-head"><h3>شروع کار با این پیج</h3><span class="sj-chip">${done} از ${req.length}</span>
        <button type="button" class="sj-linkbtn" id="onboard-hide">بعداً</button></div>
      <div class="sj-bar"><i style="width:${Math.round((done / req.length) * 100)}%;background:var(--accent)"></i></div>
      <ol>${o.steps.map((s) => `<li class="${s.done ? 'done' : ''}"><a href="${esc(s.href)}">${esc(s.label)}</a>${s.done ? ' ✓' : ''}</li>`).join('')}</ol>`;
    onboard.hidden = false;
    $('onboard-hide').addEventListener('click', () => { onboard.hidden = true; api('POST', '/api/me/onboarding', { hidden: true }).catch(() => {}); });
  }
  if (onboard) drawOnboarding();

  // ---------- the bell: alerts, weekly reports and panel notices (content/notifications.json) ----------
  const bellList = $('notif-list'), badge = $('notif-count');
  const faNum = (t) => String(t).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);  // the top bar is outside the page's digit converter
  const jAgo = (iso) => {
    const m = Math.round((Date.now() - Date.parse(iso)) / 6e4);
    if (!(m >= 0)) return '';
    return faNum(m < 60 ? Math.max(1, m) + ' دقیقه پیش' : m < 1440 ? Math.round(m / 60) + ' ساعت پیش' : Math.round(m / 1440) + ' روز پیش');
  };
  async function bell() {
    if (!bellList) return;
    let r;
    try { r = await api('GET', '/api/me/notifications'); } catch (e) { return; }
    badge.hidden = !r.unread; badge.textContent = faNum(r.unread > 9 ? '9+' : r.unread);
    if (!r.items.length) return;
    bellList.innerHTML = r.items.slice(0, 20).map((n, i) => `
      <details class="sj-notif-item${i < r.unread ? ' new' : ''}"><summary><span>${esc(n.title)}</span><small>${esc(jAgo(n.at))}</small></summary>
        <p>${esc((n.text.startsWith(n.title) ? n.text.slice(n.title.length).trim() : n.text) || n.text)}</p></details>`).join('');
  }
  if (bellList) {
    $('notif-menu').addEventListener('click', (e) => { if (!e.target.closest('a')) e.stopPropagation(); });  // open an item without closing the menu
    document.querySelector('[data-dropdown-trigger="notif-menu"]').addEventListener('click', () => {
      if (badge.hidden) return;
      badge.hidden = true;
      api('POST', '/api/me/notifications/seen').catch(() => {});
    });
    bell();
    setInterval(bell, 5 * 60 * 1000);
  }

  window.addEventListener('sj:page', (e) => {
    if (e.detail.page === 'reel') showReel(e.detail.param);
    if (e.detail.page === 'assistant') drawChat(false);
  });
})();
