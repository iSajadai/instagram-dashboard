/* Production board (#/board): every reel on its way from idea to published, saved per user in
   content/board.json. Drag a card to another column (or use its arrows on a phone); once a reel is
   out, link the card to it and the card shows the reel's numbers. Needs the panel, like tools.js. */
(function () {
  const cols = document.getElementById('board-cols');
  if (!cols) return;
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const STAGES = [['idea', 'ایده'], ['script', 'سناریو'], ['filmed', 'فیلم‌برداری شد'], ['published', 'منتشر شد']];
  const stageIx = (s) => STAGES.findIndex(([k]) => k === s);
  const code = (url) => (String(url).match(/\/(?:reels?|p|tv)\/([A-Za-z0-9_-]+)/) || [])[1] || '';
  const jDay = new Intl.DateTimeFormat('fa-IR-u-ca-persian-nu-latn', { day: 'numeric', month: 'long' });
  const jWhen = new Intl.DateTimeFormat('fa-IR-u-ca-persian-nu-latn', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tehran' });
  const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Tehran' }).format(new Date());
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

  let items = null;
  let reels = [];  // the dashboard's reels, for linking a card and showing its numbers
  const msg = (t, bad) => { const m = $('board-msg'); if (m) { m.textContent = t || ''; m.style.color = bad ? 'var(--coral)' : ''; } };

  // saves go one after another, so a quick drag-drag-drag can't land out of order
  let queue = Promise.resolve();
  const save = () => {
    const snapshot = items.map((x) => ({ ...x }));
    const done = queue.then(async () => {
      try { await api('POST', '/api/me/board', { items: snapshot }); msg('ذخیره شد ✓'); setTimeout(() => msg(''), 1500); }
      catch (e) { msg('ذخیره نشد: ' + e.message, true); throw e; }
    });
    queue = done.catch(() => {});  // one failed save doesn't block the next
    return done;
  };

  async function load() {
    try {
      const [b, d] = await Promise.all([api('GET', '/api/me/board'), fetch('/data/data.json', { credentials: 'same-origin' }).then((r) => (r.ok ? r.json() : {}))]);
      items = Array.isArray(b.items) ? b.items : [];
      const all = (d && d.reels) || [];
      const vs = all.map((r) => r.views).filter((v) => v != null).sort((a, b) => a - b);
      const med = vs.length ? vs[Math.floor((vs.length - 1) / 2)] : null;
      reels = all.filter((r) => r.url).map((r) => ({ url: r.url, published: r.published, views: r.views,
        multiple: med && r.views != null ? Math.round((r.views / med) * 10) / 10 : null,
        first: String(r.caption || '').split('\n')[0].slice(0, 70) }))
        .sort((a, b) => String(b.published).localeCompare(String(a.published)));
      draw();
    } catch (e) { cols.innerHTML = `<p class="sj-error">${esc(e.message)}</p>`; }
  }

  function cardHtml(it) {
    const i = stageIx(it.stage);
    const r = it.reel ? reels.find((x) => x.url === it.reel) : null;
    const late = it.due && it.stage !== 'published' && it.due < today();
    const chips = [];
    if (it.due) chips.push(`<span class="sj-chip${late ? ' sj-late' : ''}">${late ? 'عقب افتاده · ' : ''}${esc(jDay.format(new Date(it.due + 'T12:00:00Z')))}</span>`);
    if (r) chips.push(`<a class="sj-chip sj-chip-link" href="#/reel/${esc(code(r.url))}">${r.views == null ? 'ریل' : d3.format(',')(r.views) + ' بازدید'}${r.multiple != null ? ' · ' + r.multiple + '×' : ''}</a>`);
    else if (it.stage === 'published') chips.push('<span class="sj-chip sj-late">ریل وصل نشده</span>');
    if (it.buffer) chips.push(`<span class="sj-chip sj-chip-buffer">Buffer: ${{ idea: 'ایده', draft: 'پیش‌نویس', post: 'زمان‌بندی شد' }[it.buffer.kind] || ''}${it.buffer.due_at ? ' · ' + esc(jWhen.format(new Date(it.buffer.due_at))) : ''}</span>`);
    return `<article class="sj-bcard" draggable="true" data-id="${esc(it.id)}" tabindex="0" aria-label="${esc(it.title)}">
      <h4>${esc(it.title)}</h4>${it.hook ? `<p class="sj-bhook">${esc(it.hook)}</p>` : ''}
      ${chips.length ? `<div class="sj-bchips">${chips.join('')}</div>` : ''}
      <div class="sj-bmove">
        <button type="button" class="sj-iconbtn" data-move="-1" ${i === 0 ? 'disabled' : ''} aria-label="مرحلهٔ قبل">→</button>
        <button type="button" class="sj-linkbtn" data-edit>ویرایش</button>
        <button type="button" class="sj-iconbtn" data-move="1" ${i === STAGES.length - 1 ? 'disabled' : ''} aria-label="مرحلهٔ بعد">←</button>
      </div></article>`;
  }

  function draw() {
    if (!items) return;
    cols.innerHTML = STAGES.map(([k, label]) => {
      const list = items.filter((x) => x.stage === k);
      return `<div class="sj-col" data-stage="${k}">
        <div class="sj-col-head"><h3>${label}</h3><span class="sj-chip">${list.length}</span>
          ${k === 'idea' ? '<button type="button" class="sj-iconbtn" data-new aria-label="کارت تازه">+</button>' : ''}</div>
        <div class="sj-col-list">${list.map(cardHtml).join('') || '<p class="sj-col-empty">کارتی نیست</p>'}</div></div>`;
    }).join('');
    if (view === 'cal') drawCal();
  }

  const move = (id, stage, before) => {
    const it = items.find((x) => x.id === id);
    if (!it) return;
    const changed = it.stage !== stage;
    items = items.filter((x) => x !== it);
    it.stage = stage;
    if (changed) it.moved = Math.floor(Date.now() / 1000);
    const at = before ? items.findIndex((x) => x.id === before) : -1;
    if (at < 0) items.push(it); else items.splice(at, 0, it);
    draw(); save().catch(() => {});
    if (changed && stage === 'published' && !it.reel) edit(it.id, true);  // ask which reel it became
  };

  // drag and drop between and within columns
  let dragId = null;
  cols.addEventListener('dragstart', (e) => {
    const c = e.target.closest('.sj-bcard'); if (!c) return;
    dragId = c.dataset.id; c.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', dragId);
  });
  cols.addEventListener('dragend', () => { dragId = null; cols.querySelectorAll('.dragging, .over').forEach((el) => el.classList.remove('dragging', 'over')); });
  cols.addEventListener('dragover', (e) => {
    const col = e.target.closest('.sj-col'); if (!col || !dragId) return;
    e.preventDefault();
    cols.querySelectorAll('.sj-col.over').forEach((el) => { if (el !== col) el.classList.remove('over'); });
    col.classList.add('over');
  });
  cols.addEventListener('drop', (e) => {
    const col = e.target.closest('.sj-col'); if (!col || !dragId) return;
    e.preventDefault();
    // drop above the first card whose middle is below the pointer
    const before = [...col.querySelectorAll('.sj-bcard')].find((c) => c.dataset.id !== dragId && e.clientY < c.getBoundingClientRect().top + c.offsetHeight / 2);
    move(dragId, col.dataset.stage, before && before.dataset.id);
  });
  cols.addEventListener('click', (e) => {
    if (e.target.closest('[data-new]')) { edit(null); return; }
    const card = e.target.closest('.sj-bcard'); if (!card || e.target.closest('a')) return;
    const m = e.target.closest('[data-move]');
    if (m) { const it = items.find((x) => x.id === card.dataset.id); const n = STAGES[stageIx(it.stage) + Number(m.dataset.move)]; if (n) move(it.id, n[0]); return; }
    edit(card.dataset.id);
  });
  cols.addEventListener('keydown', (e) => { const card = e.target.closest('.sj-bcard'); if (card && e.key === 'Enter' && e.target === card) edit(card.dataset.id); });

  // the card editor
  const dlg = $('board-dialog'), form = $('board-form');
  let editing = null;
  function edit(id, askReel) {
    editing = id;
    const it = items.find((x) => x.id === id) || { title: '', hook: '', notes: '', stage: 'idea', due: '', reel: '' };
    $('board-dialog-title').textContent = id ? 'ویرایش کارت' : 'کارت تازه';
    form.elements.title.value = it.title; form.elements.hook.value = it.hook || ''; form.elements.notes.value = it.notes || '';
    form.elements.due.value = it.due || '';
    form.elements.stage.innerHTML = STAGES.map(([k, l]) => `<option value="${k}">${l}</option>`).join('');
    form.elements.stage.value = it.stage;
    const known = reels.some((r) => r.url === it.reel);
    form.elements.reel.innerHTML = '<option value="">— هنوز نه —</option>' + (it.reel && !known ? `<option value="${esc(it.reel)}">${esc(it.reel)}</option>` : '') +
      reels.map((r) => `<option value="${esc(r.url)}">${esc((r.published ? jDay.format(new Date(r.published)) + ' · ' : '') + (r.first || code(r.url)))}</option>`).join('');
    form.elements.reel.value = it.reel || '';
    $('board-delete').hidden = !id;
    $('board-to-buffer').hidden = !id;
    $('board-to-publish').hidden = !id || !window.sjPublish;
    $('board-form-msg').textContent = '';
    dlg.showModal();
    (askReel ? form.elements.reel : form.elements.title).focus();
  }
  if (dlg) {
    dlg.addEventListener('click', (e) => { if (e.target === dlg || e.target.closest('[data-close]')) dlg.close(); });
    // the form's values onto the card (a new one if it isn't on the board yet); null when the title is empty
    const apply = () => {
      const f = form.elements;
      const title = f.title.value.trim();
      if (!title) { $('board-form-msg').textContent = 'عنوان لازمه'; return null; }
      const now = Math.floor(Date.now() / 1000);
      const vals = { title, hook: f.hook.value.trim(), notes: f.notes.value.trim(), due: f.due.value || null, reel: f.reel.value, stage: f.stage.value };
      let it = items.find((x) => x.id === editing);
      if (it) { if (it.stage !== vals.stage) vals.moved = now; Object.assign(it, vals); }
      else { it = { id: 'c' + Date.now().toString(36), created: now, moved: now, ...vals }; items.push(it); }
      return it;
    };
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!apply()) return;
      dlg.close(); draw(); save().catch(() => {});
    });
    $('board-to-buffer').addEventListener('click', async () => {
      const it = apply();
      if (!it) return;
      dlg.close(); draw();
      try { await save(); } catch (e) { return; }  // Buffer remembers the card by id, so it has to be saved first
      sendToBuffer(it);
    });
    $('board-to-publish').addEventListener('click', () => {
      const it = apply();
      if (!it) return;
      dlg.close(); draw(); save().catch(() => {});
      window.sjPublish.open({ id: it.id, hook: it.hook, notes: it.notes, text: it.title });
    });
    $('board-delete').addEventListener('click', () => {
      if (!confirm('این کارت پاک بشه؟')) return;
      items = items.filter((x) => x.id !== editing);
      dlg.close(); draw(); save().catch(() => {});
    });
  }

  // sending a card to Buffer: as an idea (text only), or as a reel at a set time (needs the video's URL)
  const bdlg = $('buffer-dialog'), bform = $('buffer-form');
  let sending = null;
  const KIND_NOTE = {
    idea: 'تو بخش Ideas بافر ذخیره می‌شه؛ بعداً اونجا ویدیو رو اضافه و زمان‌بندیش می‌کنی. ویدیو لازم نیست.',
    reel: 'اینستاگرام ریل رو فقط با ویدیو قبول می‌کنه: لینک مستقیم یه فایل mp4 که عمومی باشه (مثلاً از Dropbox یا Google Drive با لینک دانلود مستقیم). Buffer سر ساعت خودش منتشرش می‌کنه.',
  };
  const syncKind = () => {
    const k = bform.elements.kind.value;
    bform.querySelectorAll('[data-for]').forEach((el) => { el.hidden = el.dataset.for !== k; });
    $('buffer-kind-note').textContent = KIND_NOTE[k];
  };
  async function sendToBuffer(it) {
    sending = it;
    const f = bform.elements;
    f.title.value = it.title;
    f.text.value = [it.hook, it.notes].filter(Boolean).join('\n\n');
    f.when.value = it.due ? it.due + 'T18:00' : '';
    f.video_url.value = ''; f.first_comment.value = ''; f.kind.value = 'idea';
    $('buffer-msg').textContent = 'در حال گرفتن کانال‌ها…';
    f.channel.innerHTML = '';
    syncKind();
    bdlg.showModal();
    try {
      const r = await api('GET', '/api/me/buffer/channels');
      f.channel.innerHTML = r.channels.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
      $('buffer-msg').textContent = '';
    } catch (e) { $('buffer-msg').textContent = e.message; }
  }
  if (bdlg) {
    bdlg.addEventListener('click', (e) => { if (e.target === bdlg || e.target.closest('[data-close]')) bdlg.close(); });
    bform.addEventListener('change', (e) => { if (e.target.name === 'kind') syncKind(); });
    bform.addEventListener('submit', async (e) => {
      e.preventDefault();
      const f = bform.elements, btn = e.submitter || bform.querySelector('[type=submit]');
      btn.disabled = true; $('buffer-msg').textContent = 'در حال فرستادن…';
      try {
        const r = await api('POST', '/api/me/buffer/send', { card: sending.id, kind: f.kind.value, channel: f.channel.value, title: f.title.value, text: f.text.value,
          when: f.when.value, video_url: f.video_url.value, first_comment: f.first_comment.value, draft: f.draft.checked });
        sending.buffer = r.sent;  // the server wrote it to the board too; keep this copy in step so the next save keeps it
        $('buffer-msg').textContent = '';
        bdlg.close(); draw();
        msg({ idea: 'تو Ideas بافر ذخیره شد ✓', draft: 'به‌صورت پیش‌نویس تو Buffer رفت ✓', post: 'تو Buffer زمان‌بندی شد ✓' }[r.sent.kind]);
      } catch (err) { $('buffer-msg').textContent = err.message; }
      btn.disabled = false;
    });
  }

  // calendar view: the Jalali month (Saturday first) with each card on its due day and Iran's
  // occasions; a holiday is marked in colour and in words. Click a day to add a card due that day.
  const calBox = $('board-cal'), viewSeg = $('board-view');
  let view = 'cols', month = null, ym = null;
  const FA = (t) => String(t).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);
  async function loadMonth(jy, jm) {
    month = await api('GET', '/api/me/calendar' + (jy ? `?jy=${jy}&jm=${jm}` : ''));
    ym = [month.jy, month.jm];
    drawCal();
  }
  function drawCal() {
    if (!month || !items) return;
    const due = {};
    items.forEach((it) => { if (it.due) (due[it.due] = due[it.due] || []).push(it); });
    const head = ['ش', 'ی', 'د', 'س', 'چ', 'پ', 'ج'].map((d, i) => `<div class="sj-jcal-wd" aria-hidden="true">${d}</div>`).join('');
    const pad = '<div class="sj-jcal-pad"></div>'.repeat(month.lead);
    const cells = month.days.map((d) => {
      const occ = d.occasions, hol = d.weekday === 6 || occ.some((o) => o.holiday);
      const cards = due[d.date] || [];
      const label = `${FA(d.jd)} ${month.title.split(' ')[0]}${hol ? '، تعطیل' : ''}${occ.length ? '، ' + occ.map((o) => o.title).join('، ') : ''}${cards.length ? '، ' + FA(cards.length) + ' کارت' : ''}`;
      return `<div class="sj-jcal-day${hol ? ' is-holiday' : ''}${d.date === month.today ? ' is-today' : ''}" role="gridcell">
        <button type="button" class="sj-jcal-num" data-day="${d.date}" aria-label="${esc(label)} — کارت تازه برای این روز">${FA(d.jd)}</button>
        ${occ.map((o) => `<span class="sj-jcal-occ${o.holiday ? ' is-holiday' : ''}" title="${o.approximate ? 'تاریخ تقریبی' : ''}">${esc(o.title)}${o.holiday ? ' · تعطیل' : ''}${o.approximate ? '؟' : ''}</span>`).join('')}
        ${cards.map((it) => `<button type="button" class="sj-jcal-card" data-card="${esc(it.id)}" data-stage="${esc(it.stage)}">${esc(it.title)}</button>`).join('')}
      </div>`;
    }).join('');
    calBox.innerHTML = `<div class="sj-jcal-head"><button type="button" class="sj-iconbtn" data-mon="-1" aria-label="ماه قبل">›</button>
      <h3 aria-live="polite">${esc(month.title)}</h3><button type="button" class="sj-iconbtn" data-mon="1" aria-label="ماه بعد">‹</button>
      <button type="button" class="sj-btn" data-mon="0">امروز</button></div>
      <div class="sj-jcal-grid" role="grid" aria-label="${esc(month.title)}">${head}${pad}${cells}</div>
      <p class="sj-small">مناسبت‌های مذهبی ۱۴۰۴ و ۱۴۰۵ از تقویم رسمی‌اند؛ سال‌های دیگه با «؟» تقریبی‌اند. قرمز یعنی تعطیل.</p>`;
  }
  if (calBox && viewSeg) {
    viewSeg.addEventListener('click', (e) => {
      const b = e.target.closest('[data-view]'); if (!b) return;
      view = b.dataset.view;
      viewSeg.querySelectorAll('[data-view]').forEach((x) => x.setAttribute('aria-selected', String(x === b)));
      calBox.hidden = view !== 'cal'; cols.hidden = view === 'cal';
      try { localStorage.setItem('sj-board-view', view); } catch (err) { /* private window */ }
      if (view === 'cal') (month ? Promise.resolve(drawCal()) : loadMonth()).catch((err) => msg(err.message, true));
    });
    calBox.addEventListener('click', (e) => {
      const m = e.target.closest('[data-mon]');
      if (m) {
        const step = Number(m.dataset.mon);
        if (!step) { loadMonth().catch((err) => msg(err.message, true)); return; }
        let [y, mo] = ym; mo += step;
        if (mo < 1) { mo = 12; y -= 1; } else if (mo > 12) { mo = 1; y += 1; }
        loadMonth(y, mo).catch((err) => msg(err.message, true));
        return;
      }
      const c = e.target.closest('[data-card]'); if (c) { edit(c.dataset.card); return; }
      const d = e.target.closest('[data-day]'); if (d) { edit(null); form.elements.due.value = d.dataset.day; }
    });
    let saved = null;
    try { saved = localStorage.getItem('sj-board-view'); } catch (err) { /* private window */ }
    if (saved === 'cal') setTimeout(() => viewSeg.querySelector('[data-view="cal"]').click(), 0);
  }

  // other pages (an idea card) add to the board through this
  window.sjBoard = {
    async add(card) {
      if (!items) await load();
      if (!items) throw new Error('بُرد باز نشد');
      const now = Math.floor(Date.now() / 1000);
      items.push({ id: 'c' + Date.now().toString(36), title: String(card.title || '').slice(0, 200), hook: String(card.hook || '').slice(0, 500),
        notes: String(card.notes || '').slice(0, 3000), stage: 'idea', reel: '', due: null, created: now, moved: now });
      draw();
      return save();
    },
  };
  // «برنامهٔ هفته رو بذار روی بُرد» — turn the week plan (studio planner) into dated idea cards
  const planBtn = $('plan-to-board');
  if (planBtn) planBtn.addEventListener('click', async () => {
    planBtn.disabled = true; msg('در حال ساختن کارت‌ها…');
    try {
      const r = await api('POST', '/api/me/plan/to-board');
      items = Array.isArray(r.items) ? r.items : items;
      draw();
      msg(r.added ? r.added + ' کارت از برنامهٔ هفته اضافه شد ✓' : 'کارتِ تازه‌ای نبود (همه از قبل روی بُردن)');
      setTimeout(() => msg(''), 3500);
    } catch (e) { msg(e.message, true); }
    finally { planBtn.disabled = false; }
  });

  window.addEventListener('sj:page', (e) => { if (e.detail.page === 'board') load(); });
})();
